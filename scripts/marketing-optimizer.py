#!/usr/bin/env python3
"""Universal PLG/CRO Marketing, Dual-Lane Bot/Human Funnel, and OpenRouter Optimizer."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from support.marketing_bot_lane import (  # noqa: E402
    evaluate_bot_appreciation,
    split_dual_lane_traffic as _split_dual_lane,
)
from support.marketing_catalog import (  # noqa: E402
    ARCHETYPES,
    DEFAULT_FORBIDDEN_JARGON,
    build_demo_funnel_variants,
    build_utm_url,
    resolve_profile,
)
from support.provider_http import open_provider_request  # noqa: E402


def generate_keywords_for_profile(
    profile: Dict[str, Any], tier: str = "all", lang: str = "all"
) -> List[Dict[str, str]]:
    name, cat, pain = profile["name"], profile["category"], profile["pain"]
    benefit, comp, url, arch = profile["benefit"], profile["competitor"], profile["url"], profile["archetype"]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "product"
    templates = [
        ("pain_point", "en", f"how to fix {pain}", "Google / Reddit", f"Solve {pain} with {name}: {benefit}."),
        ("pain_point", "ko", f"{pain} 해결 방법 추천", "Google / 블로그 / Threads", f"{pain} 문제를 {name}(으)로 바로 해결하세요: {benefit}"),
        ("workflow", "en", f"{cat} automation template", "Google / YouTube / X", f"Start with {name}: {benefit}."),
        ("workflow", "ko", f"{cat} 사용법 자동화 가이드", "Google / 기술블로그", f"{name} 핵심 가이드: {benefit}"),
        ("comparison", "en", f"best {comp} alternative for {cat}", "Google / Reddit / Product Hunt", f"Why switch from {comp} to {name}: {benefit}."),
        ("comparison", "ko", f"{comp} 대안 {cat} 비교 추천", "Google / 커뮤니티", f"{comp} 대신 {name}을 선택하는 이유: {benefit}"),
        ("activation", "en", f"{name} download start trial", "Direct / Search", f"Get {name} ({arch}): {benefit}."),
        ("activation", "ko", f"{name} 다운로드 시작하기", "Direct / Search", f"{name} 지금 바로 시작하기: {benefit}"),
    ]
    rows: List[Dict[str, str]] = []
    for t_tier, t_lang, kw, channel, hook in templates:
        if (tier != "all" and t_tier != tier) or (lang != "all" and t_lang != lang):
            continue
        rows.append({
            "product": name, "archetype": arch, "tier": t_tier, "lang": t_lang,
            "keyword": kw, "channel": channel, "landing": url, "hook": hook,
            "utm_url": build_utm_url(url, channel.split("/")[0].strip().lower(), f"organic_{arch}", f"{slug}_{t_tier}", kw),
        })
    return rows


def diagnose_bottleneck(row: Dict[str, Any], archetype: str = "saas") -> Tuple[str, str]:
    th = ARCHETYPES.get(archetype, ARCHETYPES["saas"])["thresholds"]
    views = max(1, int(row.get("landing_view", 0)))
    engaged = int(row.get("value_engaged", 0))
    activated = int(row.get("activation_click", 0))
    connected = int(row.get("account_connected", 0))
    if (engaged / views) < th["engaged"]:
        return ("headline_intent_mismatch", f"Low landing->engaged (<{int(th['engaged']*100)}%): align hero headline with search pain-point and proof.")
    if (activated / max(1, engaged)) < th["activated"]:
        return ("cta_activation_friction", f"Low engaged->activation (<{int(th['activated']*100)}%): place primary CTA/trial/download above the fold.")
    if (connected / max(1, activated)) < th["connected"]:
        return ("onboarding_signup_drop", f"Low activation->account/day-1 (<{int(th['connected']*100)}%): shorten onboarding to one immediate core action.")
    return ("healthy_funnel", "Stage conversion ratios meet archetype benchmarks; scale traffic on winning keywords.")


def compute_thompson_allocation(
    variants: Sequence[Dict[str, Any]],
    archetype: str = "saas",
    success_key: str = "activation_click",
    trial_key: str = "landing_view",
    draws: int = 4000,
    seed: int = 42,
    min_explore_floor: float = 0.10,
) -> List[Dict[str, Any]]:
    if not variants:
        return []
    rng = random.Random(seed)
    wins = [0] * len(variants)
    for _ in range(draws):
        sampled = []
        for idx, row in enumerate(variants):
            trials = max(1, int(row.get(trial_key, 0)))
            successes = min(trials, max(0, int(row.get(success_key, 0))))
            sampled.append((rng.betavariate(1.0 + successes, 1.0 + (trials - successes)), idx))
        wins[max(sampled, key=lambda pair: pair[0])[1]] += 1

    raw_shares = [w / float(draws) for w in wins]
    if any(int(v.get(trial_key, 0)) < 100 for v in variants) and len(variants) > 1:
        floor = min(min_explore_floor, 1.0 / len(variants))
        adjusted = [max(floor, s) for s in raw_shares]
        total = sum(adjusted)
        shares = [round(s / total, 4) for s in adjusted]
    else:
        shares = [round(s, 4) for s in raw_shares]

    enriched: List[Dict[str, Any]] = []
    for row, share in zip(variants, shares):
        row_arch = str(row.get("archetype") or archetype)
        views = max(1, int(row.get("landing_view", 0)))
        engaged, activated = int(row.get("value_engaged", 0)), int(row.get("activation_click", 0))
        connected, paid = int(row.get("account_connected", 0)), int(row.get("paid_converted", 0))
        code, advice = diagnose_bottleneck(row, row_arch)
        enriched.append({
            **row,
            "engaged_rate": round(engaged / views, 4),
            "activation_cvr": round(activated / views, 4),
            "account_cvr": round(connected / views, 4),
            "paid_cvr": round(paid / views, 4),
            "thompson_traffic_share": share,
            "bottleneck_code": code,
            "optimization_action": advice,
        })
    return enriched


def split_dual_lane_traffic(
    raw_visits: int, bot_share: float, human_variants: Sequence[Dict[str, Any]], archetype: str = "saas"
) -> Dict[str, Any]:
    return _split_dual_lane(raw_visits, bot_share, human_variants, archetype, compute_thompson_allocation)


def validate_copy_variant(
    variant: Dict[str, str], allowed_numbers: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    allowed = set(allowed_numbers) if allowed_numbers is not None else set(ARCHETYPES["devtool"]["defaults"]["verified_numbers"])
    text = " ".join(str(variant.get(k, "")) for k in ("headline", "subhead", "cta"))
    issues: List[str] = []
    if not str(variant.get("headline", "")).strip():
        issues.append("missing_headline")
    if not str(variant.get("cta", "")).strip():
        issues.append("missing_cta")
    lowered = text.lower()
    for term in DEFAULT_FORBIDDEN_JARGON:
        if term in lowered:
            issues.append(f"forbidden_internal_jargon:{term}")
    for num in re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text):
        if num.replace(",", "") not in allowed:
            issues.append(f"unverified_number:{num}")
    return {"valid": len(issues) == 0, "issues": issues, "variant": variant}


def generate_candidate_variants(
    profile: Dict[str, Any], bottleneck: str, model: str, live: bool = False
) -> Dict[str, Any]:
    nums = profile.get("verified_numbers", [])
    prompt = (
        f"Optimize conversion copy for product '{profile['name']}' (archetype: {profile['archetype']}, category: {profile['category']}). "
        f"Pain point: {profile['pain']}. Core benefit: {profile['benefit']}. Alternative to: {profile['competitor']}. "
        f"Detected funnel bottleneck: {bottleneck}. "
        f"Rules: 1) Lead with user-visible outcomes, no internal jargon. 2) Only use numbers from this verified ledger if citing metrics: {nums}. "
        "Return JSON: {\"variants\": [{\"headline\": \"...\", \"subhead\": \"...\", \"cta\": \"...\", \"target_keyword\": \"...\"}]}"
    )
    req = {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "payload": {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return only valid JSON matching the requested schema."},
                {"role": "user", "content": prompt},
            ],
        },
    }
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    source = "offline_verified_playbook"
    if live and api_key:
        http_req = urllib.request.Request(
            req["url"], data=json.dumps(req["payload"]).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with open_provider_request(http_req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            raw_variants = list(json.loads(body["choices"][0]["message"]["content"]).get("variants", []))
            source = f"openrouter_live:{model}"
    else:
        raw_variants = [
            {
                "headline": f"Eliminate {profile['pain']} with {profile['name']}.",
                "subhead": f"Built for {profile['category']}: {profile['benefit']}.",
                "cta": f"Start {profile['name']} Free",
                "target_keyword": f"how to fix {profile['pain']}",
            },
            {
                "headline": f"The faster alternative to {profile['competitor']}.",
                "subhead": f"Switch to {profile['name']} for {profile['benefit']}.",
                "cta": f"Try {profile['name']} Now",
                "target_keyword": f"{profile['competitor']} alternative",
            },
        ]
    return {
        "source": source,
        "profile": {"name": profile["name"], "archetype": profile["archetype"], "url": profile["url"]},
        "bottleneck": bottleneck,
        "results": [validate_copy_variant(v, allowed_numbers=nums) for v in raw_variants],
        "openrouter_request": req,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Universal Product Marketing, Dual-Lane Bot/Human Funnel & OpenRouter Optimizer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "keywords", "funnel", "bot-score", "optimize"):
        p = sub.add_parser(name)
        for flag in ("--project", "--name", "--category", "--pain", "--benefit", "--competitor", "--url"):
            p.add_argument(flag)
        p.add_argument("--archetype", default="auto", choices=["auto", "saas", "mobile_app", "ecommerce", "game", "devtool"])
        if name == "keywords":
            p.add_argument("--tier", default="all", choices=["all", "pain_point", "workflow", "comparison", "activation"])
            p.add_argument("--lang", default="all", choices=["all", "en", "ko"])
            p.add_argument("--format", default="json", choices=["json", "table"])
        elif name == "funnel":
            p.add_argument("--input")
            p.add_argument("--demo", action="store_true")
            p.add_argument("--raw-visits", type=int, default=0)
            p.add_argument("--bot-share", type=float, default=0.0)
        elif name == "optimize":
            p.add_argument("--bottleneck", default="headline_intent_mismatch")
            p.add_argument("--model", default="openai/gpt-4o-mini")
            p.add_argument("--live", action="store_true", help="Send selected product profile fields to OpenRouter; review them for private data first")
    args = parser.parse_args(argv)
    arch = "saas" if (args.archetype == "auto" and not args.project) else args.archetype
    prof = resolve_profile(args.project, arch, args.name, args.category, args.pain, args.benefit, args.competitor, args.url)
    if args.cmd == "discover":
        print(json.dumps(prof, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "keywords":
        rows = generate_keywords_for_profile(prof, args.tier, args.lang)
        if args.format == "table":
            for r in rows:
                print(f"[{r['archetype'].upper()}|{r['tier']}|{r['lang']}] {r['keyword']} -> {r['utm_url']}")
        else:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "funnel":
        data = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else build_demo_funnel_variants(prof["archetype"])
        out = split_dual_lane_traffic(args.raw_visits, args.bot_share, data, prof["archetype"]) if (args.raw_visits > 0 and args.bot_share > 0) else compute_thompson_allocation(data, archetype=prof["archetype"])
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "bot-score":
        print(json.dumps(evaluate_bot_appreciation(prof), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "optimize":
        print(json.dumps(generate_candidate_variants(prof, args.bottleneck, args.model, args.live), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
