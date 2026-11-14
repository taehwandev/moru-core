"""Declared publication is deferred past finish only when admitted, and stays owed until Git shows it."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import agent_pending_publication as pending
import claude_stop_gate
import codex_stop_gate
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_finish_check_steps import read_preflight
from agent_run_registry import transition_run
from test_agent_publication_admission import _agent_hook
from test_agent_continuation_checkpoint import initialize_git
from test_agent_run_interruption import Run


def admitted(effect, command="commit"):
    return {"route": {"command": command, "request_classification": {"intent_envelope": {
        "authority": "envelope", "schema_valid": True, "failures": [], "effective_effect": effect}}}}


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class SplitTests(unittest.TestCase):
    def test_only_an_admitted_exact_commit_route_checkpoint_defers(self):
        commit, push, pr = (
            {"checkpoint": "publication.commit"}, {"checkpoint": "publication.push"},
            {"checkpoint": "publication.pull-request"})
        blocking, deferred = pending.split_remaining(admitted("git_write"), [commit, push, pr])
        self.assertEqual([commit], deferred)
        self.assertEqual([push, pr], blocking)
        blocking, deferred = pending.split_remaining(admitted("external_write"), [commit, push, pr])
        self.assertEqual([commit, push], deferred)
        self.assertEqual([pr], blocking)  # no target: never deferred

    def test_pr_without_status_interface_can_prepare_but_stays_pending(self):
        pr = {"checkpoint": "publication.pull-request/develop", "action": "Create PR"}
        blocking, deferred = pending.split_remaining(admitted("external_write"), [pr])
        self.assertEqual([], blocking)
        self.assertEqual([pr], deferred)

    def test_other_routes_and_unadmitted_envelopes_never_defer(self):
        item = [{"checkpoint": "publication.commit"}]
        for command in ("task", "bugfix-debugging", ""):
            self.assertEqual((item, []), pending.split_remaining(admitted("external_write", command), item))
        weak = admitted("external_write")
        weak["route"]["request_classification"]["intent_envelope"]["authority"] = "assumed"
        self.assertEqual((item, []), pending.split_remaining(weak, item))
        self.assertEqual((item, []), pending.split_remaining({}, item))
        other = [{"checkpoint": "tests"}, {"checkpoint": "publication.commit-all"}, "x"]
        self.assertEqual((other, []), pending.split_remaining(admitted("external_write"), other))


STATUS_SCRIPT = (
    "import json, pathlib, sys\n"
    "state = pathlib.Path('pr-state.json')\n"
    "print(state.read_text() if state.exists() else json.dumps({'exists': False}))\n"
    "sys.exit(int(pathlib.Path('pr-fail').exists()))\n"
)


def declare_status_interface(project):
    """Commit a repo-owned read-only PR status script and its policy declaration."""
    (project / "tools").mkdir(exist_ok=True)
    (project / "tools" / "pr_status.py").write_text(STATUS_SCRIPT)
    policy = project / ".agents" / "shared" / "worktree-policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(json.dumps({
        "schema_version": 1, "require_linked_worktree": False, "protected_branches": [],
        "publication_commands": [{"argv_prefix": ["python3", "tools/create_pr.py"], "publishes": True}],
        "publication_status": {"argv": ["python3", "tools/pr_status.py", "--source", "{branch}",
                                        "--head", "{head}", "--dest", "{target}"]},
    }))
    git(project, "add", "tools", ".agents")
    git(project, "commit", "-qm", "declare pr status")


def attach_remote(project, root):
    remote = Path(root) / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(project, "remote", "add", "origin", str(remote))
    return git(project, "symbolic-ref", "--short", "HEAD")


class PullRequestSplitTests(unittest.TestCase):
    def test_pull_request_defers_with_target_even_without_provider_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            project.mkdir()
            initialize_git(project)
            pr = {"checkpoint": "publication.pull-request/develop"}
            bare = {"checkpoint": "publication.pull-request"}
            effect = admitted("external_write")
            self.assertEqual(([], [pr]), pending.split_remaining(effect, [pr], project))
            self.assertEqual(([], [pr]), pending.split_remaining(effect, [pr]))
            declare_status_interface(project)
            self.assertEqual(([], [pr]), pending.split_remaining(effect, [pr], project))
            self.assertEqual(([bare], []), pending.split_remaining(effect, [bare], project))
            self.assertEqual(([pr], []), pending.split_remaining(admitted("git_write"), [pr], project))



class PublicationObservationTests(unittest.TestCase):
    """push and PR verification for a commit made before finish and for a commit made after it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run(self.tmp.name, packet=True, writable=True, command="commit",
                       effect="external_write", authority="envelope")
        self.project, self.evidence = self.run.project, self.run.evidence
        declare_status_interface(self.project)  # committed before finish: HEAD == base_head
        self.branch = attach_remote(self.project, self.tmp.name)
        self.pr = {"checkpoint": "publication.pull-request/develop"}
        self.push = {"checkpoint": "publication.push"}

    def pr_state(self, **overrides):
        answer = {"exists": True, "state": "OPEN", "source_branch": self.branch,
                  "source_commit": git(self.project, "rev-parse", "HEAD"), "target_branch": "develop"}
        (self.project / "pr-state.json").write_text(json.dumps({**answer, **overrides}))

    def test_preexisting_commit_push_and_pr_are_observed_at_the_reviewed_head(self):
        self.assertEqual("", pending.record_pending(self.project, self.evidence, [self.push, self.pr]))
        self.assertIn("upstream", pending.settle(self.project, self.evidence, "publication.push"))
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.push"))
        self.assertEqual(["publication.pull-request/develop"], pending.outstanding(self.project, self.evidence))
        refusal = pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json")
        self.assertIn("could not be read", refusal)  # an unchecked PR is never assumed
        self.pr_state()
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual([], pending.outstanding(self.project, self.evidence))

    def test_a_commit_made_after_finish_needs_its_declared_commit_item(self):
        pending.record_pending(self.project, self.evidence, [self.push])
        (self.project / "source.txt").write_text("late\n")
        git(self.project, "commit", "-qam", "unreviewed")
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        self.assertIn("not the reviewed", pending.settle(self.project, self.evidence, "publication.push"))

    def test_new_commit_case_with_declared_commit_push_and_pr(self):
        commit = {"checkpoint": "publication.commit"}
        pending.record_pending(self.project, self.evidence, [commit, self.push, self.pr])
        self.assertIn("not advanced", pending.settle(self.project, self.evidence, "publication.push"))
        (self.project / "source.txt").write_text("new\n")
        git(self.project, "commit", "-qam", "new")
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.commit"))
        self.assertIn("upstream", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        self.pr_state()
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.push"))
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual([], pending.outstanding(self.project, self.evidence))

    def test_pr_identity_state_and_failures_are_fail_closed(self):
        pending.record_pending(self.project, self.evidence, [self.pr])
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        for override in ({"source_commit": "0" * 40}, {"source_branch": "other"},
                         {"target_branch": "main"}, {"state": "DECLINED"}, {"exists": "yes"}):
            self.pr_state(**override)
            self.assertTrue(pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"), override)
        self.pr_state()
        (self.project / "pr-state.json").unlink()
        self.assertIn("could not be read", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        (self.project / "pr-state.json").write_text("not json")
        self.assertIn("could not be read", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual(["publication.pull-request/develop"], pending.outstanding(self.project, self.evidence))

    def test_pr_without_a_pushed_head_or_with_an_untracked_script_is_refused(self):
        pending.record_pending(self.project, self.evidence, [self.pr])
        self.pr_state()
        self.assertIn("upstream", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        git(self.project, "rm", "-q", "--cached", "tools/pr_status.py")
        git(self.project, "commit", "-qm", "untrack")
        self.assertTrue(pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run(self.tmp.name, packet=True, writable=True, command="commit",
                       effect="external_write", authority="envelope")
        self.project, self.evidence = self.run.project, self.run.evidence
        self.deferred = [{"checkpoint": "publication.commit", "action": "commit"},
                         {"checkpoint": "publication.push", "action": "push"}]

    def record(self):
        return pending.record_pending(self.project, self.evidence, self.deferred)

    def test_store_failure_is_reported_never_swallowed(self):
        with patch.object(pending, "atomic_write_json", side_effect=OSError("disk")):
            self.assertIn("could not be written", self.record())
        with patch.object(pending, "_git", return_value=None):
            self.assertIn("HEAD", self.record())
        self.assertEqual(["publication.commit", "publication.push"],
                         pending.outstanding(self.project, self.evidence, self.deferred))

    def test_missing_corrupt_and_foreign_receipts_are_owed_not_complete(self):
        self.assertEqual([], pending.outstanding(self.project, self.evidence))  # nothing declared
        self.assertEqual(["publication.commit", "publication.push"],
                         pending.outstanding(self.project, self.evidence, self.deferred))
        self.assertEqual("", self.record())
        receipt = self.evidence.with_name("pending-publication.json")
        receipt.write_text("{not json")
        self.assertEqual(["receipt (unreadable)"], pending.outstanding(self.project, self.evidence))
        self.assertIn("unreadable", self.record())  # never overwritten silently
        self.assertEqual("{not json", receipt.read_text())
        receipt.unlink()
        self.assertEqual("", self.record())
        self.evidence.write_text(self.evidence.read_text() + " ")  # run changed after finish
        self.assertEqual(["receipt (foreign or malformed)"], pending.outstanding(self.project, self.evidence))
        self.assertTrue(pending.pending_reason(self.project, self.evidence))

    def test_text_is_not_proof_and_commit_is_observed_in_git(self):
        self.assertEqual("", self.record())
        self.assertEqual("", self.record())  # idempotent
        self.assertIn("not advanced", pending.settle(self.project, self.evidence, "publication.commit"))
        (self.project / "source.txt").write_text("after\n")
        git(self.project, "commit", "-qam", "work")
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.commit"))
        self.assertIn("not pending", pending.settle(self.project, self.evidence, "publication.commit"))
        self.assertEqual(["publication.push"], pending.outstanding(self.project, self.evidence))

    def test_dirty_tracked_tree_is_not_a_finished_commit(self):
        self.record()
        (self.project / "source.txt").write_text("c1\n")
        git(self.project, "commit", "-qam", "c1")
        (self.project / "source.txt").write_text("dirty\n")
        self.assertIn("uncommitted", pending.settle(self.project, self.evidence, "publication.commit"))

    def test_push_is_observed_on_the_upstream_remote(self):
        self.record()
        remote = Path(self.tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        branch = git(self.project, "symbolic-ref", "--short", "HEAD")
        git(self.project, "remote", "add", "origin", str(remote))
        (self.project / "source.txt").write_text("c1\n")
        git(self.project, "commit", "-qam", "c1")
        self.assertIn("upstream", pending.settle(self.project, self.evidence, "publication.push"))
        git(self.project, "push", "-q", "-u", "origin", branch)
        (self.project / "source.txt").write_text("c2\n")
        git(self.project, "commit", "-qam", "c2")  # local ahead of the remote
        self.assertIn("does not point", pending.settle(self.project, self.evidence, "publication.push"))
        git(self.project, "push", "-q")
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.push"))

    def test_cli_settle_refuses_without_git_proof(self):
        self.record()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = pending.main(["settle", "--project", str(self.project), "--evidence",
                                 str(self.evidence), "--checkpoint", "publication.commit"])
        self.assertEqual(2, code)
        self.assertIn("FAIL", output.getvalue())


class FinishBase(unittest.TestCase):
    """Shared fixture; its subclasses supply the tests (this base has none)."""

    RUNTIME = "claude"
    REMAINING = [{"checkpoint": "publication.commit", "action": "commit"}]

    def prepare(self):
        pass

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Run(self.tmp.name, runtime=self.RUNTIME, packet=True, writable=True, command="commit",
                       effect="external_write", authority="envelope")
        self.project, self.evidence = self.run.project, self.run.evidence
        self.prepare()
        write_continuation_checkpoint(
            project=self.project, rules=self.project, run_id=self.run.run["run_id"],
            binding_path=self.evidence, kind="initial", phase="acting",
            work={"objective": "Implement then publish", "acceptance_criteria": ["committed"],
                  "remaining_work": self.REMAINING})

    def preflight_failures(self):
        out = []
        read_preflight(self.evidence, out, project=self.project)
        return out

    def finish(self):
        hook = _agent_hook()
        args = Namespace(project=self.project, rules=self.project, evidence=self.evidence,
                         allow_vibeguard_review="", output=None, repair_cycle=0)
        results = []
        with (patch.object(hook, "run_script_main", return_value={"returncode": 0, "stdout": "", "stderr": ""}),
              patch.object(hook, "_derive_finish_gates", return_value=[]),
              patch.object(hook, "runtime_session", return_value=self.run.session),
              patch.object(hook, "finish_with_result",
                           side_effect=lambda _h, ok, details, *a, **k: results.append((ok, details)) or (0 if ok else 1)),
              patch.object(hook, "record_lifecycle_checkpoint", return_value="checkpoint"),
              patch.object(hook, "context_nudge", return_value=""),
              contextlib.redirect_stdout(io.StringIO())):
            code = hook.finish_hook(args)
        return code, results

    def stop(self, **extra):
        payload = {"session_id": "bound-session", "cwd": str(self.project), **extra}
        out = io.StringIO()
        with (patch.object(codex_stop_gate, "gate_enabled", return_value=True),
              patch.object(codex_stop_gate, "find_project_root", return_value=self.project),
              patch.object(claude_stop_gate, "gate_enabled", return_value=True),
              patch.object(claude_stop_gate, "find_project_root", return_value=self.project),
              patch.object(claude_stop_gate, "session_projects", return_value=[self.project]),
              contextlib.redirect_stdout(out)):
            (codex_stop_gate if self.RUNTIME == "codex" else claude_stop_gate).decide(payload)
        return json.loads(out.getvalue()) if out.getvalue().strip() else {}


class FinishAndStopTests(FinishBase):
    def test_commit_route_defers_but_a_task_route_does_not(self):
        self.assertFalse([f for f in self.preflight_failures() if "remains unfinished" in f])
        other = Run(tempfile.mkdtemp(dir=self.tmp.name), packet=True, writable=True, effect="external_write", authority="envelope")
        write_continuation_checkpoint(
            project=other.project, rules=other.project, run_id=other.run["run_id"],
            binding_path=other.evidence, kind="initial", phase="acting",
            work={"objective": "x", "acceptance_criteria": ["y"],
                  "remaining_work": [{"checkpoint": "publication.commit", "action": "commit"}]})
        out = []
        read_preflight(other.evidence, out, project=other.project)
        self.assertTrue([f for f in out if "remains unfinished" in f])

    def test_finish_records_the_receipt_and_stop_gates_keep_it_owed(self):
        code, results = self.finish()
        self.assertEqual(0, code, results)
        self.assertTrue(self.evidence.with_name("pending-publication.json").is_file())
        self.assertTrue(self.evidence.with_name("publication.json").is_file())
        self.assertEqual("completed", self.run.state())
        self.assertIn("publication.commit", " ".join(results[0][1]))

        first = self.stop()
        self.assertEqual("block", first["decision"])
        self.assertIn("publication.commit", first["reason"])
        repeated = self.stop(stop_hook_active=True)
        if self.RUNTIME == "codex":
            self.assertIs(False, repeated["continue"])  # stopped, never reported complete
        self.assertEqual(first["reason"], self.stop()["reason"])  # interruption preserved it

        (self.project / "source.txt").write_text("after\n")
        git(self.project, "commit", "-qam", "work")
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.commit"))
        self.assertEqual({}, self.stop())

    def test_deleted_or_corrupt_receipt_after_finish_is_still_owed(self):
        self.assertEqual(0, self.finish()[0])
        receipt = self.evidence.with_name("pending-publication.json")
        receipt.write_text("[]")
        self.assertEqual("block", self.stop()["decision"])
        receipt.unlink()
        self.assertEqual("block", self.stop()["decision"])

    def test_finish_fails_closed_when_the_receipt_cannot_be_stored(self):
        with patch.object(pending, "atomic_write_json", side_effect=OSError("disk")):
            code, results = self.finish()
        self.assertEqual(3, code)
        self.assertEqual([], results)  # no success result was reported
        self.assertNotEqual("completed", self.run.state())
        self.assertFalse(self.evidence.with_name("pending-publication.json").exists())


class PublishToPullRequestTests(FinishBase):
    """Real finish -> real git push -> declared PR status, for a commit that existed before finish."""

    REMAINING = [{"checkpoint": "publication.push", "action": "push"},
                 {"checkpoint": "publication.pull-request/develop", "action": "pull request"}]

    def prepare(self):
        declare_status_interface(self.project)
        self.branch = attach_remote(self.project, self.tmp.name)

    def pr_state(self, **overrides):
        answer = {"exists": True, "state": "OPEN", "source_branch": self.branch,
                  "source_commit": git(self.project, "rev-parse", "HEAD"), "target_branch": "develop"}
        (self.project / "pr-state.json").write_text(json.dumps({**answer, **overrides}))

    def test_finish_is_not_blocked_by_the_pull_request_and_both_stay_owed(self):
        self.assertFalse([f for f in self.preflight_failures() if "remains unfinished" in f])
        code, results = self.finish()
        self.assertEqual(0, code, results)
        self.assertEqual("completed", self.run.state())
        items = json.loads(self.evidence.with_name("pending-publication.json").read_text())["items"]
        self.assertEqual([("publication.push", "pending"), ("publication.pull-request/develop", "pending")],
                         [(i["checkpoint"], i["state"]) for i in items])
        self.assertEqual("block", self.stop()["decision"])

    def test_push_then_pr_observation_release_the_stop_gate_only_when_verified(self):
        self.assertEqual(0, self.finish()[0])
        git(self.project, "push", "-q", "-u", "origin", self.branch)
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.push"))
        after_push = self.stop()
        self.assertEqual("block", after_push["decision"])
        self.assertIn("publication.pull-request/develop", after_push["reason"])
        self.assertNotIn("publication.push", after_push["reason"])
        self.assertIn("could not be read", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual("block", self.stop()["decision"])  # interrupted: still owed
        self.pr_state(source_commit="1" * 40)
        self.assertTrue(pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual("block", self.stop()["decision"])  # wrong commit identity
        self.pr_state()
        self.assertEqual("", pending.settle(self.project, self.evidence, "publication.pull-request/develop", self.project / "pr-state.json"))
        self.assertEqual({}, self.stop())


class PullRequestWithoutTargetTests(FinishBase):
    prepare = PublishToPullRequestTests.prepare
    REMAINING = [{"checkpoint": "publication.pull-request", "action": "pr"}]

    def test_finish_blocks_without_the_declared_target(self):
        self.assertTrue([f for f in self.preflight_failures() if "remains unfinished" in f])
        self.assertEqual((0, 1), (len(pending.split_remaining(
            admitted("external_write"), self.REMAINING, self.project)[1]),
            len(pending.split_remaining(admitted("external_write"), self.REMAINING, self.project)[0])))


class CodexFinishAndStopTests(FinishAndStopTests):
    RUNTIME = "codex"


class CodexPublishToPullRequestTests(PublishToPullRequestTests):
    RUNTIME = "codex"


class FinishedPretoolAdmissionTests(unittest.TestCase):
    """The deferred publication is admitted by the receipt's effect, never by its mere declaration."""

    def admitted(self, effect, command):
        import test_claude_pretool_gate as fixtures

        fixture = fixtures.FinishAuthorizesItsOwnPublicationTests()
        with tempfile.TemporaryDirectory() as tmp:
            project = fixture._finished_project(Path(tmp))
            evidence = fixtures.gate.finished_session_evidence(project, fixture.SESSION)
            fixture._declare_pr_command(project)  # before the receipt captures the bytes
            fixtures._attest_finished_publication(project, evidence, effect=effect)
            _code, out = fixture._decide(project, command)
        return "a successful finish" in fixtures._reason(out), fixtures._reason(out)

    def test_git_write_finish_admits_commit_but_neither_push_nor_bitbucket_pr(self):
        pr = "python3 tools/bitbucket_pr/create_pr.py --source work --dest develop --ticket CCE-1"
        self.assertTrue(self.admitted("git_write", "git commit -m subject")[0])
        for command in ("git push origin work", pr):
            ok, reason = self.admitted("git_write", command)
            self.assertFalse(ok, command)
            self.assertIn("needs external_write", reason)

    def test_external_write_finish_admits_push_and_the_declared_bitbucket_pr_command(self):
        pr = "python3 tools/bitbucket_pr/create_pr.py --source work --dest develop --ticket CCE-1"
        self.assertTrue(self.admitted("external_write", "git push origin work")[0])
        self.assertTrue(self.admitted("external_write", pr)[0])


if __name__ == "__main__":
    unittest.main()
