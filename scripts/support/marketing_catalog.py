"""Universal product-archetype templates, repository auto-discovery, and bot/human dual-lane helpers."""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_FORBIDDEN_JARGON = (
    "gate-batch", "causal_v1", "decision_v1", "preflight.json",
    "worktree_fingerprint", "retrospective_repair_verify_resume",
)

ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "saas": {
        "label": "B2B / B2C Web SaaS", "schema_type": "WebApplication",
        "thresholds": {"engaged": 0.25, "activated": 0.28, "connected": 0.40},
        "defaults": {
            "name": "AcmeSaaS", "category": "workflow automation platform",
            "pain": "manual repetitive reporting", "benefit": "automated real-time dashboards in 5 minutes",
            "competitor": "legacy spreadsheets", "url": "https://example.com",
            "not_for": "teams looking for an offline desktop-only spreadsheet",
            "verified_numbers": ["5", "10", "50", "99.9"],
        },
    },
    "mobile_app": {
        "label": "Mobile & Desktop Consumer App", "schema_type": "MobileApplication",
        "thresholds": {"engaged": 0.30, "activated": 0.32, "connected": 0.45},
        "defaults": {
            "name": "DailyHabitApp", "category": "daily wellness & step tracker app",
            "pain": "forgetting daily walking goals", "benefit": "automatic streak widgets and 1-tap logging",
            "competitor": "complex fitness trackers", "url": "https://example.com/app",
            "not_for": "professional marathon telemetry requiring external chest-strap sensors",
            "verified_numbers": ["1", "3", "7", "30"],
        },
    },
    "ecommerce": {
        "label": "E-Commerce & Digital Storefront", "schema_type": "Product",
        "thresholds": {"engaged": 0.35, "activated": 0.18, "connected": 0.55},
        "defaults": {
            "name": "CraftStore", "category": "ergonomic desk setup store",
            "pain": "wrist pain from long keyboard sessions", "benefit": "split mechanical ergonomics with 30-day trial",
            "competitor": "mass-market office keyboards", "url": "https://example.com/shop",
            "not_for": "buyers seeking disposable low-profile membrane keypads",
            "verified_numbers": ["2", "30", "100"],
        },
    },
    "game": {
        "label": "Mobile / Desktop / Web Game", "schema_type": "VideoGame",
        "thresholds": {"engaged": 0.32, "activated": 0.35, "connected": 0.50},
        "defaults": {
            "name": "TycoonSim", "category": "cozy management simulation game",
            "pain": "pay-to-win timers and stressful matches", "benefit": "offline-friendly city building at your own pace",
            "competitor": "timer-locked mobile games", "url": "https://example.com/game",
            "not_for": "players seeking competitive ranked PvP esports shooters",
            "verified_numbers": ["1", "60", "100"],
        },
    },
    "devtool": {
        "label": "Developer Tool & Open-Source PLG", "schema_type": "SoftwareApplication",
        "thresholds": {"engaged": 0.28, "activated": 0.30, "connected": 0.40},
        "defaults": {
            "name": "Moru", "category": "AI coding agent workbench and verification layer",
            "pain": "CLAUDE.md token bloat and unverified Done claims",
            "benefit": "-79.7% fewer rule docs read and -94.0% fewer task steps",
            "competitor": "plain terminal CLIs and giant static rulebooks", "url": "https://getmoru.com",
            "not_for": "cloud-only multi-tenant agent hosting without local repositories",
            "verified_numbers": ["0", "0.1", "0.19", "1", "3", "4.15", "20.45", "26", "35.5", "79.7", "94.0", "96.4", "98.8", "300"],
        },
    },
}


def build_utm_url(base_url: str, source: str, medium: str, campaign: str, term: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query.update({
        "utm_source": source, "utm_medium": medium,
        "utm_campaign": campaign, "utm_term": term.lower().replace(" ", "_"),
    })
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))


def build_demo_funnel_variants(archetype: str = "saas") -> List[Dict[str, Any]]:
    d = ARCHETYPES.get(archetype, ARCHETYPES["saas"])["defaults"]
    return [
        {
            "variant_id": "variant_a_generic", "archetype": archetype, "surface": "landing",
            "headline": f"Welcome to {d['name']} — the modern {d['category']}.", "utm_term": d["category"],
            "landing_view": 420, "value_engaged": 88, "activation_click": 22, "account_connected": 9, "paid_converted": 2,
        },
        {
            "variant_id": "variant_b_pain_solution", "archetype": archetype, "surface": "landing",
            "headline": f"Stop struggling with {d['pain']} — get {d['benefit']}.", "utm_term": d["pain"],
            "landing_view": 410, "value_engaged": 192, "activation_click": 84, "account_connected": 46, "paid_converted": 15,
        },
        {
            "variant_id": "variant_c_comparison", "archetype": archetype, "surface": "comparison",
            "headline": f"Switch from {d['competitor']} to {d['name']}: {d['benefit']}.", "utm_term": f"{d['competitor']} alternative",
            "landing_view": 380, "value_engaged": 176, "activation_click": 68, "account_connected": 38, "paid_converted": 12,
        },
    ]


def discover_project_profile(project_dir: Path) -> Dict[str, Any]:
    root = project_dir.resolve()
    readme_text = ""
    seo_Candidates = (
        "README.md", "README.ko.md", "docs/PRD.md",
        "public/llms.txt", "dist/llms.txt", "src/app/llms.txt/route.ts",
        "src/components/seo/GlobalJsonLd.tsx", "src/components/seo/global-structured-data.ts",
        "src/lib/seo-public.ts", "src/seo/sitePages.ts", "src/seo/pageHtml.ts", "src/seo/siteFiles.ts",
    )
    for candidate in seo_Candidates:
        p = root / candidate
        if p.is_file():
            readme_text += "\n" + p.read_text(encoding="utf-8", errors="ignore")[:12000]
    pkg_json: Dict[str, Any] = {}
    if (root / "package.json").is_file():
        try:
            pkg_json = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except Exception:
            pkg_json = {}
    lower = readme_text.lower()
    if any(k in lower for k in ("tycoon", "gameplay", "unity", "godot", "city-builder")):
        archetype = "game"
    elif any(k in lower for k in ("add to cart", "storefront", "shopify", "ecommerce")):
        archetype = "ecommerce"
    elif any(k in lower for k in ("ios", "android", "swiftui", "jetpack compose", "pedometer", "walk")) and "cli" not in lower:
        archetype = "mobile_app"
    elif any(k in lower for k in ("publishing service", "technical blogs", "writingapplication", "next-intl", "saas", "dashboard")):
        archetype = "saas"
    elif any(k in lower for k in ("cli", "mcp", "sdk", "coding agent", "open-source", "developer")):
        archetype = "devtool"
    else:
        archetype = "saas"
    defaults = dict(ARCHETYPES[archetype]["defaults"])
    heading_match = re.search(r"^#\s+(.+)$", readme_text, flags=re.MULTILINE)
    name = heading_match.group(1).strip() if heading_match else str(pkg_json.get("name") or root.name)
    urls = [
        u.rstrip(".,;)") for u in re.findall(r"https?://[^\s)>\"'`]+", readme_text)
        if not any(skip in u for skip in ("127.0.0.1", "localhost", "schema.org", "nodejs.org"))
    ]
    primary_url = urls[0] if urls else defaults["url"]
    nums: Set[str] = set(defaults["verified_numbers"])
    for raw in re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", readme_text):
        nums.add(raw.replace(",", ""))
    paragraphs = [
        ln.strip() for ln in readme_text.splitlines()
        if ln.strip() and not ln.strip().startswith(("#", "-", "|", "`", ">", "[", "!"))
    ]
    has_table = ("|" in readme_text and "---" in readme_text) or "<table" in lower or "<dl" in lower
    has_not_for = any(
        k in lower for k in (
            "what it is not", "not for", "do not use", "do not recommend when",
            "when another option fits better", "notfit", "비목표", "아닌 것", "비추천",
        )
    )
    has_llms_or_jsonld = (
        (root / "public" / "llms.txt").is_file()
        or (root / "dist" / "llms.txt").is_file()
        or (root / "src" / "app" / "llms.txt" / "route.ts").is_file()
        or "application/ld+json" in lower
        or "json-ld" in lower
    )
    has_quickstart = "```" in readme_text or bool(urls)
    has_test_suite = (
        (root / "tests").is_dir()
        or (root / "test").is_dir()
        or "test" in pkg_json.get("scripts", {})
    )
    has_canonical_graph = (
        (root / "public" / "sitemap.xml").is_file()
        or (root / "src" / "app" / "sitemap.ts").is_file()
        or (root / "src" / "seo" / "siteFiles.ts").is_file()
        or "github.com/" in lower
    )
    return {
        "project_path": str(root), "name": name, "archetype": archetype,
        "archetype_label": ARCHETYPES[archetype]["label"],
        "schema_type": ARCHETYPES[archetype]["schema_type"],
        "category": str(pkg_json.get("description") or defaults["category"])[:120],
        "pain": defaults["pain"], "benefit": paragraphs[0][:180] if paragraphs else defaults["benefit"],
        "competitor": defaults["competitor"], "not_for": defaults["not_for"],
        "url": primary_url,
        "verified_numbers": sorted(nums)[:60],
        "signals": {
            "entity_definition": bool(paragraphs),
            "decision_boundaries": has_not_for,
            "verifiable_numeric_table": has_table and len(nums) >= 3,
            "structured_json_ld": has_llms_or_jsonld,
            "agent_executable_action": has_quickstart,
            "reproducible_benchmark_or_test_suite": has_test_suite,
            "canonical_entity_graph": has_canonical_graph,
            "external_third_party_citations": False,
        },
    }


def resolve_profile(
    project: Optional[str] = None, archetype: str = "auto", name: Optional[str] = None,
    category: Optional[str] = None, pain: Optional[str] = None, benefit: Optional[str] = None,
    competitor: Optional[str] = None, url: Optional[str] = None,
) -> Dict[str, Any]:
    if project:
        prof = discover_project_profile(Path(project))
        if archetype in ARCHETYPES:
            prof["archetype"] = archetype
            prof["archetype_label"] = ARCHETYPES[archetype]["label"]
            prof["schema_type"] = ARCHETYPES[archetype]["schema_type"]
    else:
        arch = archetype if archetype in ARCHETYPES else "saas"
        d = ARCHETYPES[arch]["defaults"]
        prof = {
            "project_path": None, "name": d["name"], "archetype": arch,
            "archetype_label": ARCHETYPES[arch]["label"], "schema_type": ARCHETYPES[arch]["schema_type"],
            "category": d["category"], "pain": d["pain"], "benefit": d["benefit"],
            "competitor": d["competitor"], "not_for": d["not_for"], "url": d["url"],
            "verified_numbers": list(d["verified_numbers"]),
            "signals": {
                "entity_definition": True, "decision_boundaries": False,
                "verifiable_numeric_table": True, "structured_json_ld": False, "agent_executable_action": True,
                "reproducible_benchmark_or_test_suite": False, "canonical_entity_graph": False,
                "external_third_party_citations": False,
            },
        }
    for k, val in (("name", name), ("category", category), ("pain", pain), ("benefit", benefit), ("competitor", competitor), ("url", url)):
        if val:
            prof[k] = val
    return prof
