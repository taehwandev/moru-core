"""Dual-lane bot/human traffic separation and Bot Appreciation / Recommendation audit."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Sequence


def split_dual_lane_traffic(
    raw_visits: int,
    bot_share: float,
    human_variants: Sequence[Dict[str, Any]],
    archetype: str,
    allocator: Callable[..., List[Dict[str, Any]]],
) -> Dict[str, Any]:
    clamped_share = min(0.9999, max(0.0, bot_share))
    bot_visits = int(round(raw_visits * clamped_share))
    human_visits = max(1, raw_visits - bot_visits)
    total_activations = sum(int(v.get("activation_click", 0)) for v in human_variants)
    denom = max(1, raw_visits + sum(int(v.get("landing_view", 0)) for v in human_variants))
    return {
        "raw_total_visits": raw_visits,
        "bot_share": clamped_share,
        "unfiltered_illusion": {
            "apparent_activation_cvr": round(total_activations / denom, 6),
            "warning": "Mixing bot crawls into human landing_view makes conversion look near 0% and blinds A/B testing.",
        },
        "agent_lane_bot_funnel": {
            "bot_crawl_view": bot_visits,
            "bot_structured_ingest": int(round(bot_visits * 0.68)),
            "bot_deep_verify": int(round(bot_visits * 0.24)),
            "ai_referral_human_visits": int(round(bot_visits * 0.012)),
            "policy": "HTTP 200 open access: serve prerendered HTML + Recommend-When table + JSON-LD so bots score and cite the product.",
        },
        "human_lane_variants": allocator(human_variants, archetype=archetype),
        "estimated_realtime_human_cohort": human_visits,
    }


def evaluate_bot_appreciation(profile: Dict[str, Any]) -> Dict[str, Any]:
    sig = profile.get("signals", {})
    weights = {
        "entity_definition": (20, "State '[Name] is a [Category] that solves [Pain] by [Benefit]' in first paragraph."),
        "decision_boundaries": (25, "Add explicit 'Recommend When' and 'Not For' rows so AI rerankers trust scope honesty."),
        "verifiable_numeric_table": (20, "Expose 3+ concrete metrics/specs in a semantic HTML <table> (not inside canvas/images)."),
        "structured_json_ld": (20, "Embed JSON-LD schema matching visible claims and provide /llms.txt or RSS discovery."),
        "agent_executable_action": (15, "Include a 1-step copyable command, direct download URL, or instant trial link."),
    }
    score = sum(w for k, (w, _) in weights.items() if sig.get(k))
    missing = [advice for k, (_, advice) in weights.items() if not sig.get(k)]
    json_ld = {
        "@context": "https://schema.org",
        "@type": profile.get("schema_type", "SoftwareApplication"),
        "name": profile["name"],
        "description": f"{profile['name']} is a {profile['category']} that solves {profile['pain']}: {profile['benefit']}.",
        "url": profile["url"],
    }
    agent_block_md = (
        f"## AI & Agent Evaluation Summary ({profile['name']})\n"
        f"- **What it is**: {profile['name']} ({profile['archetype_label']}) — {profile['category']}\n"
        f"- **Recommend when**: User needs to solve {profile['pain']} and wants {profile['benefit']}.\n"
        f"- **Do not recommend when**: User needs {profile.get('not_for', 'an unrelated category')}.\n"
        f"- **Verified metrics**: {', '.join(profile.get('verified_numbers', [])[:8])}\n"
        f"- **Direct action**: {profile['url']}"
    )
    return {
        "product": profile["name"],
        "archetype": profile["archetype"],
        "bot_recommendation_score": score,
        "signals_present": sig,
        "improvements_to_reach_100": missing,
        "ready_to_embed_agent_block_markdown": agent_block_md,
        "ready_to_embed_json_ld": json_ld,
    }
