"""The judge backend for page verification: which model answers, and the paid-call gate."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from support.provider_http import open_provider_request  # noqa: E402


ALLOW_PAID_ENV = "MORU_VERIFY_ALLOW_PAID"


def paid_calls_allowed() -> bool:
    """Paid model calls happen only when the person running the check turned them on, never because a key exists."""

    return os.environ.get(ALLOW_PAID_ENV, "").strip() == "1"


def require_paid_calls() -> None:
    if not paid_calls_allowed():
        raise RuntimeError(f"paid model calls are off; set {ALLOW_PAID_ENV}=1 to allow them for this run")


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        env = Path.home() / ".moru" / "research.env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                match = re.match(r"\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.+)", line)
                if match:
                    key = match.group(1).strip().strip("\"'")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set and ~/.moru/research.env has none")
    return key


# The judge runs on the local Codex CLI by default: it is a different model from the one that built the page,
# it uses the person's own Codex plan, and nothing is billed per call. OpenRouter is opt-in on top of that.
CODEX_DEFAULT_MODEL = "gpt-6.1-terra"
CODEX_TIMEOUT_SECONDS = 600
CODEX_ANSWER_RULE = ("\n\nAnswer from this prompt and the attached images only. Do not run commands, read files or use "
                     "any tool. Reply with the requested JSON only.")
BACKENDS = ("none", "codex", "openrouter")


def judge_settings() -> dict:
    """Which judge to use, chosen by the person running the check and never by a key or a CLI merely being present.

    Order: environment (this run only), then ``~/.moru/verify.json`` (set once, e.g. {"backend": "codex",
    "model": "<cheap model>", "effort": "low"}), then no judge at all. Without a judge only the checks that
    need no model run, and the builder is asked to look at its own page.
    """

    path = Path(os.environ.get("MORU_VERIFY_CONFIG") or Path.home() / ".moru" / "verify.json")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}

    def pick(env: str, key: str, default: str = "") -> str:
        return os.environ.get(env, "").strip() or str(saved.get(key) or default)

    name = pick("MORU_VERIFY_BACKEND", "backend", "none")
    return {"backend": name if name in BACKENDS else "none", "model": pick("MORU_VERIFY_MODEL", "model"),
            "effort": pick("MORU_VERIFY_EFFORT", "effort", "medium")}


def backend() -> str:
    return judge_settings()["backend"]


def judge_configured() -> bool:
    """Whether a model will judge the acceptance items: a judge service, or a backend chosen by the person."""

    return bool(os.environ.get("MORU_VERIFY_JUDGE_URL")) or backend() != "none"


def codex_available() -> bool:
    return shutil.which("codex") is not None


def split_content(content: object) -> tuple[str, list[bytes]]:
    """Chat-style content as one prompt text plus the images in order, each marked in the text as [image N]."""

    parts = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    texts, images = [], []
    for part in parts:
        if part.get("type") == "image_url":
            images.append(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
            texts.append(f"[image {len(images)}]")
        else:
            texts.append(str(part.get("text", "")))
    return "\n".join(texts), images


def chat_codex(content: object) -> str:
    """One judgement from the local Codex CLI: no tools, no user config, no session kept, images attached."""

    import tempfile

    prompt, images = split_content(content)
    settings = judge_settings()
    with tempfile.TemporaryDirectory(prefix="moru-codex-judge-") as tmp:
        work = Path(tmp)
        command = ["codex", "exec", "--sandbox", "read-only", "--ignore-user-config", "--ignore-rules", "--ephemeral",
                   "--skip-git-repo-check", "-C", str(work), "-m", settings["model"] or CODEX_DEFAULT_MODEL,
                   "-c", f'model_reasoning_effort="{settings["effort"]}"', "-o", str(work / "answer.txt")]
        for number, data in enumerate(images, 1):
            path = work / f"image-{number}.jpg"
            path.write_bytes(data)
            command += ["-i", str(path)]
        done = subprocess.run([*command, "-"], input=prompt + CODEX_ANSWER_RULE, capture_output=True, text=True,
                              timeout=CODEX_TIMEOUT_SECONDS, check=False)
        answer = (work / "answer.txt").read_text(encoding="utf-8") if (work / "answer.txt").is_file() else ""
    if done.returncode != 0 or not answer.strip():
        raise RuntimeError(f"codex judge failed (exit {done.returncode}): {done.stderr.strip()[-200:]}")
    return answer


def require_backend() -> None:
    """Refuse early when the chosen judge cannot run here; paid use must have been allowed on purpose."""

    chosen = backend()
    if chosen == "none":
        raise RuntimeError("no judge is configured: set MORU_VERIFY_BACKEND or ~/.moru/verify.json")
    if chosen == "openrouter":
        require_paid_calls()
        api_key()
    elif not codex_available():
        raise RuntimeError("the local codex CLI is not installed or not on PATH")


def chat(model: str, content: object, *, max_tokens: int = 3000) -> str:
    chosen = backend()
    if chosen == "none":
        raise RuntimeError("no judge is configured: set MORU_VERIFY_BACKEND or ~/.moru/verify.json")
    if chosen == "codex":
        return chat_codex(content)
    require_paid_calls()
    model = judge_settings()["model"] or model
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": content}]}).encode()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
                 "User-Agent": "moru-page-verify"})
    with open_provider_request(request, timeout=240) as response:
        return json.load(response)["choices"][0]["message"].get("content") or ""


def can_judge() -> bool:
    """Whether a derive-and-judge backend is reachable from this process."""

    if os.environ.get("MORU_VERIFY_JUDGE_URL"):
        return True
    if backend() == "none":
        return False
    if backend() == "codex":
        return codex_available()
    if not paid_calls_allowed():
        return False
    try:
        api_key()
    except RuntimeError:
        return False
    return True
