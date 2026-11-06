"""Deriving the acceptance checklist from the user's request."""

from __future__ import annotations

import json
import os
import re

from verify_backend import chat

DERIVE_MODEL = os.environ.get("MORU_VERIFY_DERIVE_MODEL", "openai/gpt-5.4")
GENERIC_ITEMS = [
    {"id": "loads-clean", "claim": "The page loads and runs without uncaught errors or failed script requests.",
     "phase": "any", "evidence": ["console"], "source": "generic"},
    {"id": "action-responds", "claim": "Using the page's main action visibly changes its state.",
     "phase": "during_action", "evidence": ["text", "screenshots"], "source": "generic"},
    {"id": "input-reaches-controls", "claim": "Pointer input reaches the visible controls and the scene: nothing invisible sits over them.",
     "phase": "any", "evidence": ["input"], "source": "generic"},
]

DERIVE_PROMPT = """You turn a user's request for a web page into acceptance items that a third party can
check by watching the running page: screenshots over time, the page's visible text, and console errors.

Rules:
- Every item states one observable fact that must be true for the request to be satisfied.
- Include conditions the request implies even when unstated: a "ready" or "before" state must differ from the
  running state; a subject said to stay visible must be in frame in every state; motion must look coherent with
  the subject (no reversed, mirrored or teleporting movement); things said to return must end where they began.
- Before answering, consider each of these generic implied conditions and include the ones that apply to this
  request (skip those that do not): (1) resting state before the action differs from the active state, with
  nothing that belongs to the active state already running; (2) a moving subject faces its direction of travel and
  never moves backwards, sideways or teleports unless asked; (3) the subject stays in frame in every camera or view
  mode the page offers, while it moves; (4) motion looks continuous, with plausible acceleration and deceleration
  rather than a constant-speed jump; (5) things said to return end where they began; (6) the offered controls
  actually change what they claim to change; (7) a vehicle that rises or descends vertically keeps its body level
  (pitch near zero) and does not stand on its tail, dive nose-first or fall like a rocket unless the request asks
  for that (a rocket or launch vehicle rises upright and may return tail-first, so judge its attitude against its flight path), and its pitch and roll stay plausible through every phase.
- Phrase each item so the available evidence can settle it. Pictures show only a few moments (the start, about 3, 6\n  and 10 seconds after the action, after each control, a touch-sized view after the action and near the end), so write\n  'at the sampled moments' for whole-sequence claims; a numeric text timeline every half second shows continuity;\n  code shows what a picture cannot. An item that no evidence can ever settle only produces a permanent failure.\n- Add nothing the request does not imply. No visual taste judgements such as "beautiful".
- At most 10 items. Each item: id (short kebab-case), claim, phase (initial | during_action | after_action | any),
  evidence (a non-empty subset of: screenshots, text, console, code). Use code for anything a screenshot cannot
  show: which way a subject's front points versus its travel direction, coordinate conventions, and whether
  things that belong to the active state are already running in the resting state.
Answer with a JSON array only.

REQUEST:
{request}
"""


def parse_array(text: str) -> list:
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError("no JSON array in the model answer")
    value = json.loads(match.group(0))
    if not isinstance(value, list):
        raise ValueError("answer is not an array")
    return value


def clean_items(raw: list) -> list[dict]:
    items = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("claim"):
            continue
        evidence = [e for e in entry.get("evidence", []) if e in {"screenshots", "text", "console", "code"}]
        items.append({"id": re.sub(r"[^a-z0-9-]+", "-", str(entry["id"]).lower()).strip("-")[:48],
                      "claim": str(entry["claim"])[:300], "phase": str(entry.get("phase") or "any"),
                      "evidence": evidence or ["screenshots"], "source": "derived"})
    return items[:10]


MENU_ITEMS = [{
    "id": "body-level-in-vertical-phases",
    "claim": ("When the vehicle rises or descends vertically (takeoff, landing, hover), its body stays level (pitch near "
              "zero); it does not stand on its tail, dive nose-first or fall like a rocket unless the request asks for that."),
    "phase": "during_action", "evidence": ["code", "screenshots"], "source": "menu",
    "applies": r"take.?off|landing|\bland\b|lift.?off|hover|ascen|descen|vtol|\bfl(?:y|ies|ight)\b|aircraft|spaceship|drone",
    # A rocket or capsule rises upright and returns tail-first by design: a level body is the wrong standard for it.
    "excludes": r"\brockets?\b|booster|launch vehicle|capsule|saturn|falcon|artemis|starship",
    "covered": r"level|pitch|nose|attitude|tail",
}, {
    "id": "scene-follows-drag-and-wheel",
    "claim": ("In the default view, dragging over the scene and scrolling the wheel move or zoom the camera as the page's "
              "orbit and zoom controls promise (compare pointer-drag-before, pointer-drag-after and pointer-wheel-after)."),
    "phase": "during_action", "evidence": ["screenshots"], "source": "menu",
    "applies": r"orbit|zoom|\bdrag|rotate|\bpan\b|camera control|touch|swipe|mouse",
    "covered": r"drag|wheel|pointer|swipe",
}]


def ensure_menu_items(request: str, items: list[dict]) -> list[dict]:
    """Add a standard item when the request calls for it and the derivation left it out.

    The derivation prompt lists generic implied conditions but the model decides which to
    include, and it omitted vehicle attitude on a request about takeoff and landing.
    """

    have = " ".join(f"{i['id']} {i['claim']}" for i in items).lower()
    extra = [{k: m[k] for k in ("id", "claim", "phase", "evidence", "source")} for m in MENU_ITEMS
             if re.search(m["applies"], request, re.I) and not re.search(m["covered"], have)
             and not (m.get("excludes") and re.search(m["excludes"], request, re.I))]
    return [*items, *extra]


def derive_checklist(request: str, *, ask=chat) -> list[dict]:
    derived = clean_items(parse_array(ask(DERIVE_MODEL, DERIVE_PROMPT.format(request=request))))
    seen = {item["id"] for item in derived}
    return ensure_menu_items(request, [*(item for item in GENERIC_ITEMS if item["id"] not in seen), *derived])
