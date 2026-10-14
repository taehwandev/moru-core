from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_delegation_plan import (
    delegation_plan_path,
    read_delegation_plan,
    validate_delegation_plan_structure,
    worker_declares_worktree_isolation,
)


def _worker(worker_id: str, scope: list[str], **overrides: Any) -> dict[str, Any]:
    worker: dict[str, Any] = {
        "id": worker_id,
        "role": f"{worker_id} role",
        "owned_scope": scope,
        "forbidden_scope": ["docs/*.md"],
        "contract": f"{worker_id} contract",
        "acceptance": [f"{worker_id} acceptance"],
        "verification": ["python3 -m unittest discover tests"],
    }
    worker.update(overrides)
    return worker


def _plan(workers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "parallel",
        "workers": workers,
        "integration_review": {
            "owner": "lead agent",
            "contract_drift_check": "compare against route gate policy",
            "final_verification": ["python3 -m unittest discover tests"],
        },
    }


class DisjointScopeTests(unittest.TestCase):
    def test_disjoint_scopes_pass(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/foo.py"]),
                _worker("b", ["scripts/bar.py"]),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))


class OverlapIsolationTests(unittest.TestCase):
    def test_overlap_passes_when_both_declare_worktree_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/shared.py"], isolation="worktree"),
                _worker("b", ["scripts/shared.py"], isolation="worktree"),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))

    def test_overlap_fails_when_only_one_declares_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/shared.py"], isolation="worktree"),
                _worker("b", ["scripts/shared.py"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))
        self.assertTrue(any("worktree isolation" in failure for failure in failures))

    def test_overlap_fails_when_neither_declares_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/shared.py"]),
                _worker("b", ["scripts/shared.py"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))

    def test_parent_child_overlap_needs_both_isolated(self) -> None:
        shared_overlap = _plan(
            [
                _worker("a", ["scripts"], isolation="worktree"),
                _worker("b", ["scripts/nested.py"], isolation="worktree"),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(shared_overlap))

        one_isolated = _plan(
            [
                _worker("a", ["scripts"], isolation="worktree"),
                _worker("b", ["scripts/nested.py"]),
            ]
        )
        self.assertTrue(
            any(
                "overlapping owned_scope" in failure
                for failure in validate_delegation_plan_structure(one_isolated)
            )
        )


class GlobScopeOverlapTests(unittest.TestCase):
    """Glob owned_scopes must not fail-open past the overlap safety check (Fix A).

    The old ``*?[]`` guard treated any glob scope as non-overlapping, so two
    non-isolated writers with a glob and a matching literal were silently
    accepted. Glob handling is now fail-closed: overlap is disproven only when the
    scopes provably address unrelated subtrees.
    """

    def test_glob_vs_matching_literal_rejected_without_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/*"]),
                _worker("b", ["scripts/agent.py"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))

    def test_two_overlapping_globs_rejected_without_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/*.py"]),
                _worker("b", ["scripts/**"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))

    def test_overlapping_globs_pass_when_both_isolated(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/*.py"], isolation="worktree"),
                _worker("b", ["scripts/**"], isolation="worktree"),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))

    def test_disjoint_globs_pass_without_isolation(self) -> None:
        plan = _plan(
            [
                _worker("a", ["docs/*.md"]),
                _worker("b", ["scripts/*.py"]),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))

    def test_glob_over_a_parent_directory_of_a_literal_overlaps(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/nested/*"]),
                _worker("b", ["scripts"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(any("overlapping owned_scope" in failure for failure in failures))


class NonCanonicalScopeTests(unittest.TestCase):
    """Path aliases must not bypass the non-isolated overlap check."""

    def test_parent_traversal_alias_is_rejected_before_dispatch(self) -> None:
        plan = _plan(
            [
                _worker("a", ["shared.py"]),
                _worker("b", ["scripts/../shared.py"]),
            ]
        )
        failures = validate_delegation_plan_structure(plan)
        self.assertTrue(
            any("normalized repo-relative POSIX path or glob" in failure for failure in failures)
        )

    def test_other_noncanonical_scope_forms_are_rejected(self) -> None:
        for scope in (
            "./shared.py",
            "scripts/./shared.py",
            "scripts//shared.py",
            "/scripts/shared.py",
            r"scripts\shared.py",
        ):
            with self.subTest(scope=scope):
                failures = validate_delegation_plan_structure(
                    _plan([_worker("a", [scope])])
                )
                self.assertTrue(
                    any(
                        "normalized repo-relative POSIX path or glob" in failure
                        for failure in failures
                    )
                )

    def test_canonical_nested_path_and_glob_remain_valid(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/nested/shared.py"]),
                _worker("b", ["docs/**/*.md"]),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))


class IsolationFieldTests(unittest.TestCase):
    def test_isolation_must_be_worktree_when_present(self) -> None:
        plan = _plan([_worker("a", ["scripts/foo.py"], isolation="container")])
        failures = validate_delegation_plan_structure(plan)
        self.assertIn(
            'agent delegation plan worker 1 isolation must be "worktree" when set',
            failures,
        )

    def test_absent_isolation_is_valid_for_disjoint_workers(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/foo.py"]),
                _worker("b", ["scripts/bar.py"]),
            ]
        )
        self.assertEqual([], validate_delegation_plan_structure(plan))


class WorkerDeclaresWorktreeIsolationTests(unittest.TestCase):
    """The dispatch-facing helper that wires plan isolation into dispatch (Fix 1)."""

    def test_returns_true_for_worktree_declared_worker(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/shared.py"], isolation="worktree"),
                _worker("b", ["scripts/shared.py"], isolation="worktree"),
            ]
        )
        self.assertTrue(worker_declares_worktree_isolation(plan, "a"))
        self.assertTrue(worker_declares_worktree_isolation(plan, "b"))

    def test_returns_false_for_shared_checkout_worker(self) -> None:
        plan = _plan(
            [
                _worker("a", ["scripts/foo.py"]),
                _worker("b", ["scripts/bar.py"]),
            ]
        )
        self.assertFalse(worker_declares_worktree_isolation(plan, "a"))

    def test_unknown_worker_id_raises_fail_closed(self) -> None:
        plan = _plan([_worker("a", ["scripts/foo.py"], isolation="worktree")])
        with self.assertRaises(ValueError):
            worker_declares_worktree_isolation(plan, "typo")

    def test_empty_worker_id_raises(self) -> None:
        plan = _plan([_worker("a", ["scripts/foo.py"])])
        with self.assertRaises(ValueError):
            worker_declares_worktree_isolation(plan, "  ")

    def test_missing_workers_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            worker_declares_worktree_isolation({}, "a")

    def test_ids_are_matched_after_trimming(self) -> None:
        plan = _plan([_worker("a", ["scripts/foo.py"], isolation="worktree")])
        self.assertTrue(worker_declares_worktree_isolation(plan, "  a  "))

    def test_duplicate_worker_id_raises_fail_closed(self) -> None:
        """Two workers sharing an id must not drive isolation from file order (Fix C)."""

        plan = _plan(
            [
                _worker("dup", ["scripts/foo.py"], isolation="worktree"),
                _worker("dup", ["scripts/bar.py"]),
            ]
        )
        with self.assertRaises(ValueError) as caught:
            worker_declares_worktree_isolation(plan, "dup")
        self.assertIn("dup", str(caught.exception))
        self.assertIn("duplicate", str(caught.exception))

    def test_invalid_json_plan_raises(self) -> None:
        with self.assertRaises(ValueError):
            worker_declares_worktree_isolation({"invalid_json": True}, "a")


class ReadDelegationPlanTests(unittest.TestCase):
    """read_delegation_plan must fail closed on an unreadable plan path."""

    def test_directory_plan_returns_invalid_json_marker(self) -> None:
        # A .moru/agent-delegation-plan.json that is a directory has exists()==True,
        # so read_text raises IsADirectoryError. Catching OSError turns that into
        # the invalid_json marker instead of a raw traceback, and structural
        # validation then reports it as not-valid-JSON.
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            plan_path = delegation_plan_path(project)
            plan_path.mkdir(parents=True, exist_ok=True)
            plan = read_delegation_plan(project)

        self.assertTrue(plan.get("invalid_json"))
        self.assertEqual(str(plan_path), plan.get("path"))
        self.assertEqual(
            ["agent delegation plan is not valid JSON"],
            validate_delegation_plan_structure(plan),
        )

    def test_absent_plan_returns_empty_dict(self) -> None:
        # Guard against over-tightening: a genuinely absent plan is still the
        # no-plan state, not an unreadable one.
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual({}, read_delegation_plan(Path(temp_dir)))


if __name__ == "__main__":
    unittest.main()
