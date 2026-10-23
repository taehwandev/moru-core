import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def _load_marketing_optimizer():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "marketing-optimizer.py"
    spec = importlib.util.spec_from_file_location("marketing_optimizer", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UniversalMarketingOptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_marketing_optimizer()

    def test_supports_all_five_business_archetypes(self):
        for arch in ("saas", "mobile_app", "ecommerce", "game", "devtool"):
            prof = self.mod.resolve_profile(archetype=arch)
            self.assertEqual(prof["archetype"], arch)
            kws = self.mod.generate_keywords_for_profile(prof, lang="ko")
            self.assertEqual(len(kws), 4)
            self.assertTrue(all(r["archetype"] == arch for r in kws))
            self.assertTrue(all(f"utm_medium=organic_{arch}" in r["utm_url"] for r in kws))

    def test_auto_discovers_any_repository_archetype_and_verified_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# WalkMate\n\nA daily iOS and Android pedometer walk app that boosts steps by 42% in 14 days.\n"
                "Visit https://walkmate.example.com\n",
                encoding="utf-8",
            )
            prof = self.mod.resolve_profile(project=str(root))
            self.assertEqual(prof["name"], "WalkMate")
            self.assertEqual(prof["archetype"], "mobile_app")
            self.assertEqual(prof["url"], "https://walkmate.example.com")
            self.assertIn("42", prof["verified_numbers"])
            self.assertIn("14", prof["verified_numbers"])

    def test_diagnose_bottleneck_respects_archetype_thresholds(self):
        code_ecom, _ = self.mod.diagnose_bottleneck(
            {"landing_view": 200, "value_engaged": 60, "activation_click": 20, "account_connected": 15},
            archetype="ecommerce",
        )
        self.assertEqual(code_ecom, "headline_intent_mismatch")

        code_saas, _ = self.mod.diagnose_bottleneck(
            {"landing_view": 200, "value_engaged": 60, "activation_click": 25, "account_connected": 15},
            archetype="saas",
        )
        self.assertEqual(code_saas, "healthy_funnel")

    def test_thompson_sampling_allocates_majority_to_high_converting_variant(self):
        demo = self.mod.build_demo_funnel_variants("saas")
        allocated = self.mod.compute_thompson_allocation(demo, archetype="saas", seed=42)
        self.assertEqual(len(allocated), 3)
        by_id = {r["variant_id"]: r for r in allocated}
        self.assertLess(by_id["variant_a_generic"]["thompson_traffic_share"], 0.05)
        self.assertGreater(
            by_id["variant_b_pain_solution"]["thompson_traffic_share"]
            + by_id["variant_c_comparison"]["thompson_traffic_share"],
            0.95,
        )

    def test_dual_lane_traffic_separates_99_99_percent_bots_from_human_cvr(self):
        demo = self.mod.build_demo_funnel_variants("saas")
        split = self.mod.split_dual_lane_traffic(5000, 0.9999, demo, archetype="saas")
        self.assertEqual(split["raw_total_visits"], 5000)
        self.assertGreaterEqual(split["agent_lane_bot_funnel"]["bot_crawl_view"], 4999)
        self.assertGreater(split["agent_lane_bot_funnel"]["ai_referral_human_visits"], 0)
        # Human lane Thompson Sampling remains intact and unaffected by 5,000 bot hits
        human_by_id = {r["variant_id"]: r for r in split["human_lane_variants"]}
        self.assertGreater(human_by_id["variant_b_pain_solution"]["activation_cvr"], 0.15)

    def test_evaluate_bot_appreciation_scores_signals_and_generates_json_ld(self):
        prof = self.mod.resolve_profile(project=str(Path(__file__).resolve().parent.parent))
        audit = self.mod.evaluate_bot_appreciation(prof)
        self.assertGreaterEqual(audit["bot_recommendation_score"], 50)
        self.assertLessEqual(audit["bot_recommendation_score"], 90)
        self.assertEqual(audit["score_breakdown"]["on_page_readiness_max"], 70)
        self.assertEqual(audit["score_breakdown"]["off_page_corroboration_max"], 30)
        self.assertEqual(audit["score_breakdown"]["local_repo_ceiling"], 90)
        self.assertEqual(audit["ready_to_embed_json_ld"]["@context"], "https://schema.org")
        self.assertIn("Recommend when", audit["ready_to_embed_agent_block_markdown"])
        self.assertIn("Do not recommend when", audit["ready_to_embed_agent_block_markdown"])

    def test_validate_copy_variant_locks_to_project_specific_verified_numbers(self):
        good = self.mod.validate_copy_variant(
            {
                "headline": "Boost daily walking consistency by 42% in 14 days.",
                "subhead": "Automatic habit streaks on your lock screen.",
                "cta": "Download WalkMate",
            },
            allowed_numbers=["14", "42"],
        )
        self.assertTrue(good["valid"], good["issues"])

        bad_number = self.mod.validate_copy_variant(
            {
                "headline": "Boost walking speed by 999% in 2 days.",
                "subhead": "Fast results.",
                "cta": "Download",
            },
            allowed_numbers=["14", "42"],
        )
        self.assertFalse(bad_number["valid"])
        self.assertIn("unverified_number:999", bad_number["issues"])

    def test_cli_entrypoints_work_for_any_archetype_and_repo(self):
        for argv in (
            ["discover", "--project", str(Path(__file__).resolve().parent.parent)],
            ["keywords", "--archetype", "ecommerce", "--name", "DeskCraft", "--lang", "ko"],
            ["funnel", "--archetype", "game", "--raw-visits", "5000", "--bot-share", "0.9999", "--demo"],
            ["bot-score", "--project", str(Path(__file__).resolve().parent.parent)],
            ["optimize", "--archetype", "mobile_app", "--name", "TodayWalk"],
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.mod.main(argv)
            self.assertEqual(rc, 0)
            parsed = json.loads(buf.getvalue())
            self.assertTrue(parsed)


if __name__ == "__main__":
    unittest.main()
