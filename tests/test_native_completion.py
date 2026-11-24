"""Native completion policy through the actual private binary protocol."""
from datetime import date
from difflib import SequenceMatcher
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import tempfile
import unicodedata
import unittest
from unittest.mock import Mock, patch

import agent_doctor as doctor
import agent_project_memory as project_memory
import agent_execution_capsule_bindings as capsule_bindings
import agent_execution_capsule as capsule
import agent_review_structure as structure
import agent_review_merge_baseline as merge_baseline
import agent_android_action_boundary as android
import agent_review_removals as removals
import agent_review_purpose as purpose
import agent_directory_fingerprint as directory_fingerprint
import agent_worktree_fingerprint as worktree_fingerprint
import agent_execution_capsule_state as capsule_state
import agent_execution_capsule_validation as capsule_validation
from agent_continuation_checkpoint import write_continuation_checkpoint
from agent_execution_capsule_state import atomic_write_json
from agent_route_state import preflight_evidence_sha256, route_fingerprint
from agent_local_delivery import LocalDeliveryProof, _capture_identities
from agent_pending_publication import (
    _git, _legacy_local_head, _legacy_local_head_python, _load, _load_python, _new_record, _observe, _observed_record, _store,
    _remote_head, outstanding, pending_reason, record_pending, split_remaining,
)
from agent_publication_status import _observe_pull_request_python, observe_pull_request, observe_upstream
from native_pretool_support import environment, prepare
from support.completion_native import completion_native
from support.native_probe_transport import NativeProbe
from support import stable_launcher
from support import project_type_detection
from test_agent_run_interruption import Run
from test_agent_workspace_policy import load_collect_failures


def contract(revision=1, **overrides):
    return {"revision": revision, "items": [{"id": "r1", "outcome": "Deliver the plan", "owner": "lead",
        "gate": "tests", "artifacts": ["plan.md"], **overrides}]}


class NativeCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-completion-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty = self.base / "empty"
        self.empty.mkdir()

    def raw(self, op, value, **overrides):
        return subprocess.run([str(self.entry.with_name("moru-hook-native")), str(self.entry), "--completion-probe", op],
            input=json.dumps(value).encode() if not isinstance(value, bytes) else value,
            env={**self.env, "PATH": str(self.empty), **overrides}, cwd=self.project, capture_output=True, timeout=10)

    def check(self, op, value):
        result = self.raw(op, value)
        self.assertEqual((0, b""), (result.returncode, result.stderr), result)
        envelope = json.loads(result.stdout)
        self.assertEqual(1, envelope["schema_version"])
        return envelope["result"]

    def test_structure_merge_baseline_matches_native_parent_precedence(self):
        parent = "a" * 64
        selected = ["same\n한.py", "head.py", "incoming.py", "mode.py", "absent.py"]
        refs = [
            ("incoming.py\0mode.py\0", "same\n한.py\0head.py\0incoming.py\0mode.py\0"),
            ("head.py\0mode.py\0", "same\n한.py\0head.py\0incoming.py\0mode.py\0outside.py\0"),
        ]

        def review(**overrides):
            responses = [(0, parent + "\n"), (0, ""), (0, ""), *[(0, value) for row in refs for value in row]]
            for key, response in overrides.items():
                responses[int(key.removeprefix("r"))] = response
            runner = Mock(side_effect=[{"returncode": status, "stdout": stdout} for status, stdout in responses])
            result = merge_baseline.inherited_merge_paths(self.project, [Path(path) for path in selected], runner)
            return result, runner.call_count

        expected = {"same\n한.py": parent, "head.py": "HEAD", "incoming.py": parent}
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            merge_baseline, "_python_inherited_paths", side_effect=AssertionError("Python classified parents"),
        ):
            self.assertEqual((expected, 7), review())
        with patch.object(NativeProbe, "request", return_value={"inherited": {"outside.py": parent}}):
            self.assertEqual((expected, 7), review())
        with patch.object(NativeProbe, "request", side_effect=AssertionError("Native saw uncertain Git state")):
            self.assertEqual(({}, 3), review(r1=(1, "")))
            self.assertEqual(({}, 3), review(r2=(0, "unmerged\0")))
            self.assertEqual(({}, 7), review(r6=(1, "")))
        malformed = {"parent": parent, "selected": selected, "refs": [["", "head.py"], refs[1]]}
        self.assertEqual(125, self.raw("structure-merge-baseline", malformed).returncode)

    def test_structure_compose_action_findings_complete_native_and_match_python(self):
        cases = [
            "@Composable fun A() { }",
            "fun A() { nav.navigate(route) }",
            "@Composable fun A() {\nnav\n .navigate (route)\nToast . makeText(ctx)\n}",
            "@Composable fun A() { viewModel.navigate(route); router?.navigate(route); navigate { } }",
            "@Composable fun A(vm: MyViewModel) { vm.showToast(x); ViewModel.showToast(x); vm::navigate }",
            "@Composable fun A(onNavigate: () -> Unit) { onNavigate(); Screen(onClick = onNavigate) }",
            "@Composable fun A(onNavigate: () -> Unit?) { onNavigate(); Screen(onClick=onNavigateNext) }",
            "@Composable fun A() { Screen(onClick = onShowNotice(), onTap = onShowToast) }",
            "@Composable fun A() { onA=onShowToast=onShowNotice; nav::navigate::showToast; ::navigate }",
            "@Composable fun A() { outer.navigate(navigate(route)); nav::navigateUp; nav::navigateUpMore }",
            "@Composable fun A() { viewModel.effects.collect { nav.navigate(x); clickable { nav.navigate(y) } } }",
            "@Composable fun A() { NoticeEffectLifecycleCollector(effects=flow,onEffect={\nnav.navigate(x)\nonTap={nav.navigate(y)}\n}) }",
            '@Composable fun A() { "Toast.makeText(x)"; /* nav::navigate */ repoRepository?.load(); RouteEvent.Open }',
            "import androidx.compose.runtime.Composable as UI\n@UI fun A(화면: VMViewModel) = 화면.navigate(x)",
            "@Composable fun A() {\n" + "\n" * 8 + "nav.navigate(a); nav.navigate(b); repository.fetch()\n}",
        ]
        path = Path("Screen.kt")
        scan = android.AndroidActionBoundary.failures
        for source in cases:
            with patch.object(NativeProbe, "request", return_value=None):
                expected = scan(path, source)
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                android, "_kotlin_code_for_review", side_effect=AssertionError("Python evaluated Compose"),
            ):
                self.assertEqual(expected, scan(path, source), source)
            with patch.object(NativeProbe, "request", return_value={"action_findings": [[True, 9]]}):
                self.assertEqual(expected, scan(path, source))

    def test_structure_compose_source_findings_match_python(self):
        cases = [
            "CustomRouteEvent.Open; RouteEvent.Close()",
            "slot is RouteEvent.Open; slot as NoticeEffect.Close",
            "slot as? NoticeEffect.Open; slot is app.RouteEvent.Close",
            "island NavigationEvent.Foo; 가is NoticeEffect.Close",
            "slot is\x1cRouteEvent.Open; RouteEvent.\n\nClose",
            "RouteEvent.NoticeEffect.Open; RouteEvent.가; RouteEvent.A한",
            "repository?.load(); dao(); api.reload()",
            "app.ModelRepository.\n load(); customDataSource?.값()",
            "repository? .load(); repository.load; repository?.load<T>()",
            "LoadUseCase(); loadUseCase(); _readUseCase(); 한UseCase()",
            "repository(dao()); app.UseCase.invoke()",
            "ApiClient.repository(); myRepo.fetch(); LookalikeRepositoryX.call()",
            '/* repository.load() */ "RouteEvent.Open"; repository /* note */ ?.load()',
        ]
        cls = android.AndroidActionBoundary
        for body in cases:
            source = f"@Composable fun Screen() {{ {body} }}"
            masked = android._mask_kotlin_literals(source)
            expected = [list(android._source_findings(cls, masked[start:end]))
                        for _, start, end in cls._bodies(masked)]
            native = self.check("kotlin-literal-mask", {
                "source": source, "unicode": unicodedata.unidata_version, "source_findings": True,
            })
            self.assertEqual(expected, native["source_findings"], source)

        source = (
            "@Composable fun Screen() {\n"
            "val type = model is RouteEvent.Open\n"
            "val event = RouteEvent.Close\n"
            "repository?.load()\n}"
        )
        path = Path("Screen.kt")
        invalid = {"code": source, "bodies": [list(span) for span in cls._bodies(source)],
                   "source_findings": [[[False], []]]}
        with patch.object(NativeProbe, "request", return_value=invalid):
            expected = cls.failures(path, source)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            android, "_source_findings", side_effect=AssertionError("Python searched source violations"),
        ):
            self.assertEqual(expected, cls.failures(path, source))
        self.assertEqual(["3", "4"], [finding.split(":")[1] for finding in expected])

    def test_structure_compose_viewmodel_scopes_are_local_and_match_python(self):
        cases = [
            ("vm: app.ScreenViewModel?", "vm.uiEffects.collectLatest { inner { run() } }"),
            ("vm: app.ViewModel.Inner", "other.vm.effects.collect { }"),
            ("vm: ViewModel", "vm?.effects?.collect { }"),
            ("vm: ScreenViewModel<T> = make()", "vm\n .sideEffects\n .collect\n { }"),
            ("vm: ScreenViewModelSuffix", "vm.effects.collect { }"),
            ("vm: app . ScreenViewModel", "vm.effects.collect { }"),
            ("상태: 모델ViewModel", "상태\x1c.uiEffects.collect { }"),
            ("vm: ViewModel", "othervm.effects.collect { }; vmβ.effects.collect { }"),
            ("", "ViewModel.effects.collect { }; otherViewModel.effects.collect { }"),
            ("", "viewModel.effects.collect { }; viewModel.effects.collector { }"),
            ("other: Foo, foo: a.AViewModel.BViewModel", "foo.effects.collect {"),
            ("a: AViewModel, a: BViewModel", "a.effects.collect { }; a.other.collect { }"),
        ]
        cls = android.AndroidActionBoundary
        for parameters, body in cases:
            source = f"@Composable fun Screen({parameters}) {{ {body} }}"
            masked = android._mask_kotlin_literals(source)
            expected = []
            for signature, start, end in cls._bodies(masked):
                names, _, collectors = android._viewmodel_scopes(cls, masked[signature:start], masked[start:end], None)
                expected.append({"names": names, "collectors": [list(scope) for scope in collectors]})
            native = self.check("kotlin-literal-mask", {
                "source": source, "unicode": unicodedata.unidata_version, "viewmodel_scopes": True,
            })
            self.assertEqual(expected, native["viewmodel_scopes"], source)

        source = (
            "@Composable fun First(ui: a.ScreenViewModel) {\n"
            "ui.effects.collect { nav.navigate(consumed) }\n}\n"
            "@Composable fun Second() {\n"
            "ui.effects.collect { nav.navigate(untyped) }\n}"
        )
        path = Path("Screen.kt")
        invalid = {"code": source, "bodies": [list(span) for span in cls._bodies(source)],
                   "viewmodel_scopes": [{"names": [False], "collectors": []}] * 2}
        with patch.object(NativeProbe, "request", return_value=invalid):
            expected = cls.failures(path, source)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            cls, "_regions", side_effect=AssertionError("Python determined collector scopes"),
        ):
            self.assertEqual(expected, cls.failures(path, source))
        self.assertEqual(1, len(expected))
        self.assertTrue(expected[0].startswith("Screen.kt:5:"))

    def test_structure_compose_callback_scopes_match_python(self):
        callbacks = [
            "", "on = { x }", "onClick={ onTap = { y } }", "on한\x1c=\n{ y }",
            "xonClick={ x } onClickβ = { y }", 'clickable("}") { onTap={ y } }',
            "combinedClickable(x(y)) { x }", "clickable((unbalanced) { x }",
            "clickable(x = { onTap={x} }) { y }", "clickable(args) nope { x }",
            "clickable() combinedClickable() { x }", "clickable { onClick={ missing",
            "NoticeEffectLifecycleCollector ( effects = 흐름, onEffect = { onClick={x} } )",
            "NoticeEffectLifecycleCollector(effects = vm.flow, onEffect = { x })",
            "xNoticeEffectLifecycleCollector(effects=flow,onEffect={x})",
        ]
        for snippet in callbacks:
            source = "@Composable fun Screen() {\n" + snippet + "\n}"
            native = self.check("kotlin-literal-mask", {
                "source": source, "unicode": unicodedata.unidata_version, "callback_scopes": True,
            })
            masked = android._mask_kotlin_literals(source)
            cls = android.AndroidActionBoundary
            expected = [
                [[list(span) for span in group] for group in android._callback_scopes(cls, masked[start:end])]
                for _, start, end in cls._bodies(masked)
            ]
            self.assertEqual(expected, native["callback_scopes"], snippet)

        source = (
            "@Composable fun Screen() {\n"
            "NoticeEffectLifecycleCollector(effects = flow, onEffect = {\n"
            "    nav.navigate(collected)\n"
            "    clickable { nav.navigate(direct) }\n"
            "})\n}"
        )
        scan = android.AndroidActionBoundary.failures
        path = Path("Screen.kt")
        with patch.object(NativeProbe, "request", return_value={
            "code": source, "bodies": [list(span) for span in android.AndroidActionBoundary._bodies(source)],
            "aliases_normalized": True, "callback_scopes": [[[[False, 2]], []]],
        }):
            expected = scan(path, source)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            android, "_callback_scopes", side_effect=AssertionError("Python found callback scopes"),
        ):
            self.assertEqual(expected, scan(path, source))
        self.assertEqual(1, len(expected))
        self.assertTrue(expected[0].startswith("Screen.kt:4:"))

    def test_structure_compose_aliases_match_order_and_adjust_spans(self):
        compose = "import androidx.compose.runtime.Composable as UI\n"
        event = "import app.RouteEvent as E\n"
        aliased = compose + event + "@UI fun Screen() {\nval e = E.Open\n}"
        cases = [
            aliased, compose + "@UIβ fun Screen() {} @UI\u0301 fun Next() {}",
            event + "E Eβ βE E\u0301 _E E_ `E`",
            event + "import app.NoticeEffect as E\nval e = E.Open",
            compose + "import app.RouteEvent as Composable\n@UI fun Screen() {}",
            "prefiximport\x1capp.InnerRouteEvent.Next as 경로\n경로.Open",
            "import app.RouteEventIgnored as E\nE.Open",
            "import app.SomeType as E\nE.Open",
            '/* import app.RouteEvent as E */ val s = "E.Open"\nE.Open',
            "import app.NavigationEvent as import import app.NoticeEffect as X\nX.Open",
        ]
        for source in cases:
            masked = android._mask_kotlin_literals(source)
            expected = android._normalize_aliases(masked)
            native = self.check("kotlin-literal-mask", {
                "source": source, "unicode": unicodedata.unidata_version, "normalize_aliases": True,
            })
            self.assertEqual(masked, native["code"])
            self.assertIs(native["aliases_normalized"], True)
            self.assertEqual(expected, native.get("normalized_code", masked))
            self.assertEqual(
                [list(span) for span in android.AndroidActionBoundary._bodies(expected)], native["bodies"],
            )
        for source, version in [(event + "한 E.Open", "unknown"), (event * 600, unicodedata.unidata_version)]:
            native = self.check("kotlin-literal-mask", {
                "source": source, "unicode": version, "normalize_aliases": True,
            })
            self.assertEqual(source, native["code"])
            self.assertNotIn("aliases_normalized", native)

        path = Path("Screen.kt")
        scan = android.AndroidActionBoundary.failures
        with patch.object(NativeProbe, "request", return_value=None):
            expected = scan(path, aliased)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            android, "_normalize_aliases", side_effect=AssertionError("Python expanded aliases"),
        ), patch.object(android.AndroidActionBoundary, "_bodies", side_effect=AssertionError("Python parsed body")):
            self.assertEqual(expected, scan(path, aliased))
        self.assertEqual(1, len(expected))
        self.assertTrue(expected[0].startswith("Screen.kt:4:"))

    def test_structure_compose_body_spans_match_python(self):
        cases = [
            "", "@Composable fun Broken(", "@Composable fun Screen():",
            "@Composable fun Screen() { nested { }", "@Composable fun Screen() =",
            "@ComposableX fun Screen() {}", "@Composableβ fun Screen() {}",
            "@Composable fun\x1c이름.화면(x: (Int) -> Unit): State<T>? {}",
            "@Composable fun Screen(a: @Composable () -> Unit) { a() }",
            "@Composable\n@Composable\nfun Screen() {}",
            "@androidx.compose.runtime.Composable fun Screen() = foo()\nprivate fun Next() {}",
            "@Composable fun Screen() = foo()\ninternal funny()\n@Other fun Next() {}",
            "@Composable fun Screen() = foo()\n  fun Indented() {}\nfun End() {}",
            "@Composable ffun Screen() {}\nfun Next() {}", '@Composable fun Screen() = "{"',
            "@Composable fun Screen(): T where T : Any {}",
            '@Composable fun Screen(x: Int = f(g(")"))) { use(x) }',
            '/* @Composable */ fun Fake() {} @Composable fun Real() = one(); two()',
            "@Composable fun `Screen Name`() {}\nfun Next() {}",
        ]
        for source in cases:
            code = android._mask_kotlin_literals(source)
            expected = [list(span) for span in android.AndroidActionBoundary._bodies(code)]
            self.assertEqual(
                {"code": code, "bodies": expected},
                self.check("kotlin-literal-mask", {"source": source, "unicode": unicodedata.unidata_version}),
            )
        source = "@Composable fun 이름() {}"
        self.assertEqual({"code": source}, self.check("kotlin-literal-mask", {"source": source, "unicode": "unknown"}))

        path = Path("Screen.kt")
        plain = "@Composable fun Screen() {\nnav.navigate(route)\n}"
        alias = "import androidx.compose.runtime.Composable as UI\n@UI fun Screen() {\nnav.navigate(route)\n}"
        scan = android.AndroidActionBoundary.failures
        with patch.object(NativeProbe, "request", return_value=None):
            expected = scan(path, plain), scan(path, alias)
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(android.AndroidActionBoundary, "_bodies", side_effect=AssertionError("Python parsed body")):
                self.assertEqual(expected[0], scan(path, plain))
            self.assertEqual(expected[1], scan(path, alias))
        self.assertEqual([1, 1], list(map(len, expected)))

    def test_structure_kotlin_literal_mask_preserves_python_offsets(self):
        cases = [
            "", "plain 한🙂 e\u0301", "// 🙂\r\nvisible", "// EOF", "/",
            "a/* 한 /* inner */ end */b", "a/* /* unterminated", "a/*/\nb",
            'a""" 한\n// "" \'\n"""b', 'a"""unterminated\n"', 'a"x\\"🙂"b',
            "a'\\''b", "\"trailing escape\\", '"\\\nnext"tail',
            'a"é\u2028🙂\r"b', 'a"/* still string */"b',
            'a"""$id ${call("/*🙂*/")}"""b', 'a"${call("x")}"b',
        ]
        for source in cases:
            self.assertEqual(
                {"code": android._mask_kotlin_literals(source)},
                self.check("kotlin-literal-mask", {"source": source}),
            )

        source = '@Composable\nfun Screen() {\n/* 🙂 */ val s = "nav.navigate(fake)"\nnav.navigate(real)\n}'
        path = Path("Screen.kt")
        with patch.object(NativeProbe, "request", return_value={"code": "wrong length"}):
            expected = android.AndroidActionBoundary.failures(path, source)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            android, "_mask_kotlin_literals", side_effect=AssertionError("Python masked Kotlin"),
        ):
            self.assertEqual(expected, android.AndroidActionBoundary.failures(path, source))
        self.assertEqual(1, len(expected))
        self.assertTrue(expected[0].startswith("Screen.kt:4:"))

    def test_structure_android_action_delta_preserves_shifted_findings_only(self):
        baseline = [
            "@Composable", "fun Screen() {", "    nav.navigate(oldRoute)",
            "    repository.load()", "}",
        ]
        current = ["// summary", *baseline[:3], "    repository.reload()", "}"]
        run = Mock(return_value={"returncode": 0, "stdout": "\n".join(baseline)})
        args = (self.project, Path("Screen.kt"), current, {"status": "R", "previous_path": "Old.kt"}, run)
        with patch.object(NativeProbe, "request", return_value={"inherited": [1, 1]}):
            expected = structure.android_action_delta_failures(*args)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            structure, "SequenceMatcher", side_effect=AssertionError("Python aligned baseline"),
        ):
            self.assertEqual(expected, structure.android_action_delta_failures(*args))
        run.assert_called_with(["git", "show", "HEAD:Old.kt"], self.project)
        self.assertEqual((1, 1), tuple(map(len, expected)))
        self.assertIn("Screen.kt:5:", expected[0][0])
        self.assertTrue(expected[1][0].startswith("unchanged baseline violation: Screen.kt:4:"))

        previous = ["x", "", "x", "y"]
        current = ["x", "x", "", "y", "x"]
        prior_keys = [(1, "a"), (3, "a"), (3, "b"), (0, "a"), (12, "a")]
        current_keys = [(line, reason) for line in range(1, 6) for reason in ("a", "b")] + [None]
        self.assertEqual(
            {"inherited": structure._inherited_action_findings(previous, current, prior_keys, current_keys)},
            self.check("structure-action-delta", {
                "previous": previous, "current": current, "prior_keys": prior_keys, "current_keys": current_keys,
            }),
        )

    def test_structure_move_matching_matches_python_candidate_and_block_ties(self):
        rng = random.Random(19)
        cases = [
            ([], [["x"], [], []]),
            (list("tide"), [list("diet"), list("ted"), list("ted")]),
            (list("diet"), [list("tide"), list("diex"), list("diet")]),
            (["한", "", "}"] * 100, [["한", "", "}"] * 99 + ["다"], ["한"] * 300]),
            (list("abcde"), [list("abxde"), list("abcye")]),
        ]
        alphabet = ["", "x", "y", "한"]
        for _ in range(40):
            current = rng.choices(alphabet, k=rng.randrange(20))
            cases.append((current, [rng.choices(alphabet, k=rng.randrange(20)) for _ in range(5)]))
        for current, sources in cases:
            matchers = [SequenceMatcher(None, source, current, autojunk=False) for source in sources]
            index = max(range(len(sources)), key=lambda i: matchers[i].ratio())
            expected = (index, sum(block.size for block in matchers[index].get_matching_blocks()))
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                structure, "SequenceMatcher", side_effect=AssertionError("Python scored candidates"),
            ):
                self.assertEqual(expected, structure._best_source_match(current, sources))
            with patch.object(NativeProbe, "request", return_value={"best": [len(sources), 0]}):
                self.assertEqual(expected, structure._best_source_match(current, sources))
        repeated = [""] * 2100
        declined = self.raw("structure-move-matching", {"current": repeated, "candidates": [repeated + ["x"]]})
        self.assertEqual((125, b""), (declined.returncode, declined.stdout))

    def test_structure_owner_findings_keep_baseline_budgets_and_role_transitions(self):
        common = {
            "public_count": 2, "previous_public_count": 2, "public_labels": "A@1, B@2",
            "visible_count": 5, "previous_visible_count": 5, "visible_labels": "A@1, B@2, C@3",
            "role_labels": "A@1, B@2", "roles": ["data", "ui"], "previous_roles": ["data", "ui"],
        }
        rows = [
            {**common, "path": "legacy.py"},
            {**common, "path": "growth.py", "previous_public_count": 1, "visible_count": 6,
             "roles": ["data", "domain", "ui"]},
            {**common, "path": "new-mix.py", "previous_roles": ["ui"]},
            {**common, "path": "improving.py", "previous_roles": ["data", "domain", "ui"]},
        ]
        expected = [failure for row in rows for failure in purpose._owner_findings(row)]
        request = {
            "limit": 20, "paths": [[row["path"], "M"] for row in rows],
            "owners": {"files": rows, "public_limit": purpose.MAX_PUBLIC_TOP_LEVEL_OWNERS,
                       "visible_limit": purpose.MAX_TOP_LEVEL_OWNERS, "role_pairs": purpose.MIXED_ROLE_BLOCKS},
        }
        with patch.dict(os.environ, self.env, clear=True):
            _, layout = structure._file_findings([], source_layout=request)
        self.assertEqual(expected, layout["owner_failures"])
        self.assertEqual(["growth.py", "growth.py", "growth.py", "new-mix.py"],
                         [failure.split(" ", 1)[0] for failure in expected])

    def test_structure_package_roles_match_grouped_language_roots_and_order(self):
        paths = {
            "plain/Services/util/Foo.kt": "A",
            "shared/src/main/kotlin/Feature.kt": "A",
            "shared/src/main/java/helpers/Feature.java": "A",
            "shared/lib/src/Feature.dart": "A",
            "shared/lib/src/Feature.swift": "M",
            "shared/Sources/Feature.swift": "A",
            "shared/Sources/UTIL/Feature.swift": "A",
            ".agents/shared/task.py": "A",
            ".agents/shared/manager/task.py": "A",
            "src/service/existing.py": "M",
            "a/util/file.py": "A",
            "a-/helper/file.py": "A",
        }
        expected = purpose.package_role_failures(
            self.project, [Path(path) for path in paths], {path: {"status": status} for path, status in paths.items()},
            structure.review_source_path, structure.test_exempt_path,
        )
        payload = {"limit": 20, "paths": list(paths.items()), "generic_parts": sorted(purpose.GENERIC_PACKAGE_PARTS)}
        with patch.dict(os.environ, self.env, clear=True):
            _, layout = structure._file_findings([], source_layout=payload)
        self.assertEqual(expected, layout["package_failures"])
        self.assertEqual(
            [".agents/shared/manager", "a/util", "a-/helper", "plain/Services/util",
             "shared/Sources/UTIL", "shared/src/main/java/helpers"],
            [failure.partition(" contains ")[0] for failure in expected],
        )
        payload["paths"].append(("한글/util/item.py", "A"))
        with patch.dict(os.environ, self.env, clear=True):
            _, layout = structure._file_findings([], source_layout=payload)
        self.assertIsNone(layout["package_failures"])

    def test_structure_net_deletions_include_excluded_and_missing_paths(self):
        metadata = {
            "zapped.py": {"additions": 0, "deletions": 80},
            "src.py": {"additions": 5, "deletions": 54},
            "docs/한글.md": {"additions": 2, "deletions": 52},
            "tool.config.py": {"additions": 3, "deletions": 64},
            "unknown.py": {"additions": None, "deletions": 99},
        }
        expected = structure.net_deletion_findings(metadata)
        paths = [Path(path) for path in metadata]
        (self.project / "src.py").touch()
        (self.project / "tool.config.py").touch()
        discovery = {"path_metadata": metadata, "command_errors": []}
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            structure, "net_deletion_findings", side_effect=AssertionError("Python calculated net deletions"),
        ):
            selected = structure._review_sources(self.project, paths, discovery)
            report = structure._structure_result(
                discovery, selected, max_file_lines=500, max_block_lines=120, max_added_lines=300,
            )
        self.assertEqual([Path("src.py")], selected)
        self.assertEqual(expected, report["net_deletions"])
        self.assertEqual(["docs/한글.md", "tool.config.py", "zapped.py"],
                         [row["path"] for row in report["net_deletions"]])
        self.assertNotIn("_net_deletions", report["discovery"])

        oversized = {"path_metadata": {"src.py": {"additions": -(2 ** 63), "deletions": 0}},
                     "command_errors": []}
        with patch.dict(os.environ, self.env, clear=True):
            selected = structure._review_sources(self.project, [Path("src.py")], oversized)
        self.assertNotIn("_net_deletions", oversized)
        report = structure._structure_result(
            oversized, selected, max_file_lines=500, max_block_lines=120, max_added_lines=300,
        )
        self.assertEqual(2 ** 63, report["net_deletions"][0]["net"])

    def test_structure_removal_matching_preserves_consumption_ties_and_redaction(self):
        sensitive = "def token_fixture():"
        diff = "\n".join((
            "diff --git a/0-first.py b/0-first.py", "--- a/0-first.py", "+++ b/0-first.py",
            "-right body", "-shared body", "-" + sensitive, "+shared body",
            "diff --git a/second.py b/second.py", "--- a/second.py", "+++ b/second.py",
            "-shared body", "-shared body",
            "diff --git a/z.py b/z.py", "--- a/z.py", "+++ b/z.py", "+right body",
            "diff --git a/b.py b/b.py", "--- a/b.py", "+++ b/b.py", "+shared body",
            "diff --git a/a.py b/a.py", "--- a/a.py", "+++ b/a.py", "+shared body",
        ))
        def classify():
            result = [{"path": path} for path in ("0-first.py", "second.py", "missing.py")]
            removals.classify_net_deletions(
                result, project=self.project, run_command=lambda *_: {"returncode": 0, "stdout": diff},
                review_paths=None, review_commits=("base", "head"), path_metadata={},
            )
            return result

        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = classify()
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            removals, "classify_removal", side_effect=AssertionError("Python matched occurrences"),
        ), patch.object(NativeProbe, "request", wraps=NativeProbe.request) as request:
            self.assertEqual(expected, classify())
            protocol, operation, payload = request.call_args.args
            self.assertEqual(("--completion-probe", "structure-removal-matching"), (protocol, operation))
            self.assertNotIn(sensitive, json.dumps(payload))
            self.assertNotIn("shared body", json.dumps(payload))
        self.assertEqual(["z.py", "a.py"], expected[0]["moved_to"])
        self.assertEqual(["[sensitive-looking content omitted]"], expected[0]["sample_lines"])
        self.assertEqual(["0-first.py", "b.py"], expected[1]["moved_to"])
        self.assertEqual("unavailable", expected[2]["classification"])

    def test_structure_source_layout_keeps_counts_warning_order_and_path_prefix(self):
        limit = structure.REVIEW_NEW_SOURCE_FILE_PRESSURE_LIMIT
        additions = [f"src/새 파일-{index}.py" for index in reversed(range(limit + 1))]
        copies = [f"src/copy-{index}.py" for index in reversed(range(9))]
        for added in (additions, additions[:-1]):
            with self.subTest(added=len(added)):
                paths = [[path, "A"] for path in added] + [[path, "C"] for path in copies]
                paths += [["renamed.py", "R"], ["unknown.py", None]]
                legacy = {"strict_checked_paths": [path for path, _ in paths], "warnings": []}
                metadata = {path: {"status": status} for path, status in paths}
                structure.flag_new_source_file_sprawl(legacy, metadata)
                structure.flag_content_preserving_source_copies(legacy, metadata)
                with patch.dict(os.environ, self.env, clear=True):
                    findings, layout = structure._file_findings([], source_layout={"limit": limit, "paths": paths})
                self.assertEqual([], findings)
                self.assertEqual({
                    "added": legacy["new_source_file_count"],
                    "copied": legacy["content_preserving_source_copy_count"],
                    "warnings": legacy["warnings"],
                }, layout)
                self.assertEqual(2 if len(added) > limit else 1, len(layout["warnings"]))
                self.assertIn(", ".join(copies[:8]) + "; ...", layout["warnings"][-1])

    def test_structure_file_size_batch_keeps_python_thresholds_and_order(self):
        files = [
            {"path": f"src/{index}.py", "line_count": lines, "metadata": metadata,
             "max_file_lines": 500, "max_added_lines": 300, "review_warning_file_lines": 300}
            for index, (lines, metadata) in enumerate((
                (500, {"status": "A", "additions": 300}),
                (501, {"status": "A"}),
                (600, {"status": "R", "additions": 302, "deletions": 303}),
                (600, {"status": "C", "additions": 302, "deletions": 302}),
                (600, {"status": "A", "initial_full_build": True}),
                (650, {"status": "M"}),
            ))
        ]
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = [list(row) for row in structure._file_findings(files)[0]]
        self.assertEqual({"findings": expected}, self.check("structure-file-size", {"files": files}))

        paths = [Path("a.py"), Path("b.py"), Path("tests/test_example.py")]
        metadata = {str(path): {"status": "A"} for path in paths}
        (self.project / paths[0]).write_text("def example():\n" + "    pass\n" * 5)
        (self.project / paths[1]).write_bytes(b"\xff")
        (self.project / paths[2]).parent.mkdir()
        (self.project / paths[2]).write_bytes(b"\xef\xbb\xbf" + b"# test\r\n" * 7)

        def review():
            with patch.object(structure, "changed_source_paths", return_value=(
                {"command_errors": [], "path_metadata": metadata}, paths,
            )), patch.object(structure, "_add_cross_path_findings"):
                return structure.structure_review(
                    self.project, 5, 3, lambda *_: {"returncode": 1},
                    max_added_lines=2, review_commits=("base", "head"),
                )

        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            reference = review()
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            structure, "_check_file_size", side_effect=AssertionError("Python checked file size"),
        ), patch.object(
            structure, "_prepared_blocks", side_effect=AssertionError("Python computed new block spans"),
        ), patch.object(structure, "_block_review_findings", side_effect=AssertionError("Python checked blocks")):
            self.assertEqual(reference, review())
        self.assertEqual(["a.py", "a.py", "a.py:1", "tests/test_example.py"],
                         [message.split(" ", 1)[0] for message in reference["failures"]])
        self.assertIn("per-file addition limit is 6", reference["failures"][-1])
        self.assertTrue(reference["warnings"][0].startswith("b.py "))

    def test_structure_brace_declarations_match_legacy_grammar(self):
        path = Path("source.ts")
        headers = [
            "public final class Excluded {", "export default class Excluded {", "enum Excluded {",
            "sealed interface Excluded {", "abstract fun skipped() {", "publicish ignored() {",
            "function f() {", "export async function f() {", "override fun f() {", "fn f() {",
            "fun f() {", "public{", "export function {", "if (true) {",
            "const x = p => {", "export const y: F = async <T>(f: (v: T) => T): R => {",
            "let y = asyncname => {", "var y = <T>(value: T) => {",
            "const y = (x = 1) => {", "const y = (f: ((v: X))) => {",
            "const y = async () : => {", "const y = async () :  => {",
            "const y = async => {", "const y = {", "  // function ignored() {",
        ]
        lines = [[header, '  use("한글 }"); /* { */', "}"] for header in headers]
        expected = [[{key: block[key] for key in ("line", "label", "span")}
                     for block in structure.oversized_blocks(path, body, 1)] for body in lines]
        files = [{**structure._block_span_input(path, body), "limit": 1} for body in lines]
        self.assertTrue(all(file["kind"] == "brace-source" for file in files))
        result = self.check("structure-block-spans", {"files": files})
        for header, legacy, native in zip(headers, expected, result["blocks"], strict=True):
            with self.subTest(header=header):
                self.assertEqual(legacy, native)
        unicode_file = {**structure._block_span_input(path, ["export function 한() {", "  use();", "}"]),
                        "limit": 1}
        expected_unicode = [[{"line": 1, "label": "export function 한() {", "span": 3}]]
        self.assertEqual({"blocks": expected_unicode},
                         self.check("structure-block-spans", {"files": [unicode_file]}))
        self.assertEqual(125, self.raw("structure-block-spans", {
            "files": [{**unicode_file, "unicode": "different"}],
        }).returncode)

    def test_structure_style_blocks_match_masking_and_selector_rules(self):
        fixtures = [
            [
                "@media screen {", '  .한[data-text="}"] {', '    content: "a' + chr(92) + '"}b";',
                "    /* }", "       { */", '    color: red; // }', "  }", "}",
                ".inline { color: red; }", "/* selector { */",
            ],
            [
                "." + "한" * 85 + " {", '  content: "continued' + chr(92),
                '  }";', "}", ".unfinished {", "  // }", "  color: blue;",
            ],
            ["'unterminated", ".kept {", "  color: blue;", "}"],
            [],
        ]
        for suffix in (".css", ".scss", ".sass"):
            path = Path(f"source{suffix}")
            inputs = [{**structure._block_span_input(path, lines), "limit": 1} for lines in fixtures]
            self.assertTrue(all(item["kind"] == "style-source" for item in inputs))
            expected = [[{
                key: block[key] for key in ("line", "label", "span")
            } for block in structure.oversized_blocks(path, lines, 1)] for lines in fixtures]
            self.assertEqual({"blocks": expected}, self.check("structure-block-spans", {"files": inputs}))
            self.assertEqual([6, 4, 3], [block["span"] for blocks in expected[:2] for block in blocks])
            self.assertEqual(80, len(expected[1][0]["label"]))
            self.assertEqual([2], [block["line"] for block in expected[2]])

    def test_structure_python_declarations_match_unicode_regex_profile(self):
        lines = [
            "class Outer:", "\tasync\tdef inner(self):", "    pass", "  # 한국어",
            "@decorator", "def\u00a0tail_2():", "    pass", "defx ignored():", "    pass",
            "async def9 ignored():", "    pass",
        ]
        def prepared(source):
            return {**structure._block_span_input(Path("source.py"), source), "limit": 1}

        expected = [{
            key: block[key] for key in ("line", "label", "span")
        } for block in structure.oversized_blocks(Path("source.py"), lines, 1)]
        self.assertEqual(["inner", "tail_2"], [block["label"] for block in expected])
        self.assertEqual({"blocks": [expected]}, self.check("structure-block-spans", {"files": [prepared(lines)]}))

        unicode_lines = [
            "def prefé²():", "    pass", "def a\u0301():", "    pass", "def 한():", "    pass",
        ]
        unicode_input = prepared(unicode_lines)
        self.assertEqual({"blocks": [[
            {"line": 1, "label": "prefé²", "span": 2}, {"line": 3, "label": "a", "span": 2},
        ]]}, self.check("structure-block-spans", {"files": [unicode_input]}))
        mismatch = {**unicode_input, "unicode": "different"}
        declined = self.raw("structure-block-spans", {"files": [mismatch]})
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        file = {"path": "source.py", "line_count": 2, "metadata": {"status": "A"}, "max_file_lines": 500,
                "max_added_lines": 300, "review_warning_file_lines": 300,
                "block_spans": {**mismatch, "initial": False}}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            reference = structure._file_findings([file])
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(reference, structure._file_findings([file]))
        self.assertIn("block `prefé²`", reference[0][0][0][0])

    def test_structure_existing_block_spans_keep_baseline_reads_lazy(self):
        source = ["def example():", "    pass", "    pass", "    pass"]
        short = ["def tiny():", "    pass", "count = 1", "count = 2"]
        baseline = {"old.py": "\n".join(source), "origin.py": "def example():\n    pass\n"}
        def review():
            files = [
                {"path": name, "line_count": len(lines), "metadata": metadata,
                 "max_file_lines": 500, "max_added_lines": 300, "review_warning_file_lines": 300,
                 "block_spans": {**structure._block_span_input(Path(name), lines),
                                 "limit": 2, "initial": False}}
                for name, lines, metadata in (
                    ("short.py", short, {"status": "M"}),
                    ("renamed.py", source, {"status": "R", "previous_path": "old.py"}),
                    ("copied.py", source, {"status": "C", "previous_path": "origin.py"}),
                    ("missing.py", source, {"status": "M"}),
                )
            ]
            reads = []
            def run(command, _cwd):
                reads.append(command)
                name = command[-1].removeprefix("HEAD:")
                return {"returncode": 0, "stdout": baseline[name]} if name in baseline else {"returncode": 1}
            structure._attach_block_baselines(self.project, files, run)
            return [list(row) for row in structure._file_findings(files)[0]], reads

        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected, reads = review()
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            structure, "_prepared_blocks", side_effect=AssertionError("Python computed block spans"),
        ):
            self.assertEqual((expected, reads), review())
        self.assertEqual([["git", "show", f"HEAD:{name}"] for name in ("old.py", "origin.py", "missing.py")], reads)
        self.assertEqual([[], []], expected[0])
        self.assertIn("previously 4", expected[1][1][0])
        self.assertIn("copied.py:1", expected[2][0][0])
        self.assertIn("missing.py:1", expected[3][0][0])

    def test_structure_block_spans_match_indentation_and_masked_brace_boundaries(self):
        python_lines = [
            "class Outer:", "    def inner(self):", "        pass", "# keep the comment in the span",
            "", "    @decorator", "    def second(self):", "        pass", "async def tail():", "    pass",
        ]
        brace_lines = [
            "function one() {", '  const text = "}";', "  /* } */", "  if (yes) {",
            "    call();", "  }", "}", "function both() {}", "function unfinished() {", "  call();",
        ]
        rows = []
        for filename, lines, initial in (
            ("source.py", python_lines, True), ("source.ts", brace_lines, False),
        ):
            rows.append({
                "path": filename, "line_count": len(lines), "metadata": {"status": "A"},
                "max_file_lines": 500, "max_added_lines": 300, "review_warning_file_lines": 300,
                "block_spans": {**structure._prepare_block_spans(Path(filename), lines),
                                "limit": 2, "initial": initial},
            })
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = [list(row) for row in structure._file_findings(rows)[0]]
        self.assertEqual({"findings": expected}, self.check("structure-file-size", {"files": rows}))
        self.assertEqual([], expected[0][0])
        for warning, span in zip(expected[0][1], [8, 5], strict=True):
            self.assertIn(f"spans {span} lines", warning)
        self.assertEqual(1, len(expected[1][0]))
        self.assertIn("spans 7 lines", expected[1][0][0])

    def test_structure_block_findings_match_baselines_and_initial_builds(self):
        facts = {
            "limit": 10, "initial": False,
            "current": [
                {"line": 1, "label": "repeat", "span": 20},
                {"line": 22, "label": "repeat", "span": 21},
                {"line": 44, "label": "새 함수", "span": 11},
            ],
            "previous": [{"label": "repeat", "span": 30}, {"label": "repeat", "span": 20}],
        }
        file = {"path": "src/file.py", "line_count": 54, "metadata": {"status": "A"},
                "max_file_lines": 50, "max_added_lines": 60, "review_warning_file_lines": 50}
        files = [
            {**file, "actions": [["action failure"], ["action warning"]], "blocks": facts},
            {**file, "path": "src/initial.py", "metadata": {"initial_full_build": True},
             "blocks": {**facts, "initial": True, "previous": []}},
        ]
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = [list(row) for row in structure._file_findings(files)[0]]
        self.assertEqual({"findings": expected}, self.check("structure-file-size", {"files": files}))
        failures, warnings = expected[0]
        self.assertEqual("action failure", failures[1])
        self.assertIn("src/file.py:22", failures[2])
        self.assertEqual("action warning", warnings[1])
        self.assertIn("previously 20", warnings[2])
        self.assertEqual([], expected[1][0])
        self.assertEqual(4, len(expected[1][1]))

    def test_structure_source_paths_match_legacy_exclusions_and_file_types(self):
        names = [
            "src/File.RS", "build/ignored.rs", "Build/kept.rs", "Generated/ignored.rs",
            "pigeons/schema.DART", "Pigeons/schema.dart", "vite.CONFIG.TS", "setup.PY",
            "src/한.py", "third_party/example/file.py", "dir.rs", "missing.rs", "link.rs",
            "src/.rs", "README.md",
        ]
        paths = [Path(name) for name in names]
        for path in paths:
            target = self.project / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.name == "dir.rs":
                target.mkdir()
            elif path.name == "link.rs":
                target.symlink_to(self.project / "src" / "File.RS")
            elif path.name != "missing.rs":
                target.touch()
        vendor = self.project / "third_party" / "example"
        (vendor / "README.md").write_text("Upstream commit sha-256 license")
        (vendor / "LICENSE").touch()
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = structure._review_sources(self.project, paths)
        self.assertEqual([Path(name) for name in (
            "src/File.RS", "Build/kept.rs", "Pigeons/schema.dart", "src/한.py", "link.rs",
        )], expected)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            structure, "review_source_path", wraps=structure.review_source_path,
        ) as fallback:
            self.assertEqual(expected, structure._review_sources(self.project, paths))
            self.assertEqual([Path("src/한.py"), Path("third_party/example/file.py")],
                             [call.args[1] for call in fallback.call_args_list])
        (self.project / ".gitattributes").write_text("src/File.RS linguist-generated\n")
        structure._declares_generated.cache_clear()
        structure.linguist_generated_path.cache_clear()
        self.addCleanup(structure._declares_generated.cache_clear)
        self.addCleanup(structure.linguist_generated_path.cache_clear)
        with patch.dict(os.environ, self.env, clear=True), patch.object(NativeProbe, "request") as request:
            self.assertEqual([], structure._review_sources(self.project, [Path("src/File.RS")]))
            request.assert_not_called()

    def test_structure_diff_preserves_paths_and_falls_back_on_truncation(self):
        status = "R100\0src/old\t.py\0src/new\n.py\0C75\0src/from.py\0src/한.py\0A\0 src/bin.py \0"
        counts = "1\t2\t\0src/old\t.py\0src/new\n.py\0"
        counts += "0\t3\t\0src/from.py\0src/한.py\0-\t-\t src/bin.py \0"
        expected = {
            "status": [list(row) for row in structure._parse_name_status(status)],
            "numstat": [list(row) for row in structure._parse_numstat(counts)],
        }
        self.assertEqual(expected, self.check("structure-diff", {"status": status, "numstat": counts}))

        def record(numstat):
            metadata = {}
            structure._record_diff({"returncode": 0, "stdout": status}, {"returncode": 0, "stdout": numstat},
                                   set(), metadata, [], "git diff")
            return metadata

        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            reference = record(counts)
            truncated_reference = record(counts[:-1])
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(structure, "_parse_name_status", side_effect=AssertionError("Python decoded paths")):
                self.assertEqual(reference, record(counts))
            declined = self.raw("structure-diff", {"status": status, "numstat": counts[:-1]})
            self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
            self.assertEqual(truncated_reference, record(counts[:-1]))

    def test_preflight_failures_match_python_order_and_unicode_limit(self):
        collect = load_collect_failures()
        cases = (
            ({"returncode": 1, "stdout": "   A\x1cB\u0085", "stderr": "é" * 500},
             {"missing": ["skill.md"]}, "ignored parse error", False),
            ({"returncode": 1, "stderr": "\u3000\t"}, None, "", False),
            ({"returncode": 0}, {"missing": ["skill.md"]}, "parse error", True),
            ({"returncode": 0}, {"missing": ["skill.md"]}, "", True),
            ({"returncode": 0}, {"missing": {"skill.md": True}}, "", False),
        )
        for route, payload, parse_error, review_only in cases:
            with self.subTest(route_status=route["returncode"], parse_error=parse_error, review_only=review_only):
                args = (route, payload, parse_error, {"returncode": 128, "review_only": review_only},
                        {"returncode": 1}, ["hook failed", "hook failed"])
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = collect(*args)
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                    NativeProbe, "request", wraps=NativeProbe.request,
                ) as request:
                    self.assertEqual(expected, collect(*args))
                    request.assert_called_once()
                    protocol, operation, prepared = request.call_args.args
                    self.assertEqual(("--completion-probe", "preflight-failures"), (protocol, operation))
                if isinstance(prepared["route_missing"], dict):
                    declined = self.raw(operation, prepared)
                    self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
                else:
                    self.assertEqual({"failures": expected}, self.check(operation, prepared))
        with patch.dict(os.environ, self.env, clear=True), patch.object(NativeProbe, "request") as request:
            self.assertEqual([], collect({"returncode": 0}, {}, "", {"returncode": 0}, {"returncode": 0}, []))
            request.assert_not_called()

    def test_doctor_reads_project_stacks_and_managed_instructions_in_rust(self):
        agents = self.project / "AGENTS.md"
        agents.write_bytes(f"한글\r\n{doctor.MANAGED_END}\r\n{doctor.MANAGED_BEGIN}\r\n".encode())
        (self.project / "Demo.xcodeproj").mkdir()
        (self.project / ".helper.py").symlink_to(self.project / "missing")
        for name in ("package.json", "build.gradle", "Cargo.toml", "go.mod"):
            (self.project / name).write_text("{}")
        args = [str(self.entry), "doctor", "--project", str(self.project), "--format", "json"]
        reference = subprocess.run(args, cwd=self.project, capture_output=True, timeout=20,
                                   env={**self.env, "MORU_LAUNCHER_BACKEND": "python"})
        native = subprocess.run(args, cwd=self.project, capture_output=True, timeout=20, env=self.env)
        self.assertEqual((0, reference.stdout, reference.stderr),
                         (native.returncode, native.stdout, native.stderr))
        report = json.loads(native.stdout)
        self.assertEqual(["swift", "node", "gradle", "rust", "go", "python"], report["stacks"])
        self.assertEqual({"agents_md_present": True, "managed_routing_block": True},
                         report["instructions"])
        self.assertEqual({key: report[key] for key in ("stacks", "instructions")},
                         self.check("doctor-project", {"project": str(self.project)}))
        self.assertEqual({
            "files": {key: report[key] for key in ("stacks", "instructions")},
            "permissions": report["detected_permission_count"],
            "active_runs": report["state"]["active_runs"],
        }, self.check("doctor-project-facts", {"project": str(self.project)}))
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = doctor.inspect_project_health(self.project)
        separate = {"_inspect_project_files", "_permission_count", "_active_run_count"}
        with patch.dict(os.environ, self.env, clear=True), patch.multiple(
            doctor, **{name: unittest.mock.Mock(side_effect=AssertionError(name)) for name in separate},
        ):
            self.assertEqual(expected, doctor.inspect_project_health(self.project))

    def test_doctor_preserves_unreadable_and_linked_instructions_behavior(self):
        agents = self.project / "AGENTS.md"
        payload = {"project": str(self.project)}
        agents.write_bytes(b"\xff")
        declined = self.raw("doctor-project", payload)
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        declined = self.raw("doctor-project-facts", payload)
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(UnicodeDecodeError):
            doctor.inspect_project_health(self.project)

        other = self.base / "managed.md"
        other.write_text(f"{doctor.MANAGED_BEGIN}\n{doctor.MANAGED_END}\n")
        agents.unlink()
        agents.symlink_to(other)
        declined = self.raw("doctor-project", payload)
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        with patch.dict(os.environ, self.env, clear=True):
            instructions = doctor.inspect_project_health(self.project)["instructions"]
        self.assertEqual({"agents_md_present": True, "managed_routing_block": True}, instructions)

    def test_doctor_node_manifest_scan_preserves_permission_deduplication_and_errors(self):
        (self.project / "package.json").write_text('{"scripts":{"test":"root","install":"other"}}')
        for folder, text in (
            ("app", '{"scripts":{"test":"child","test *":"overlap","test ":"space","한글":"unicode"}}'),
            ("empty", "{}"),
            ("broken", "{"),
            ("node_modules", '{"scripts":{"ignored":"excluded"}}'),
            ("app/deep", '{"scripts":{"ignored":"too-deep"}}'),
        ):
            directory = self.project / folder
            directory.mkdir()
            (directory / "package.json").write_text(text)

        payload = {"project": str(self.project)}
        scripts = self.check("doctor-node-manifests", payload)["scripts"]
        self.assertEqual(["test", "install"], scripts[0])
        self.assertCountEqual([["test", "test *", "test ", "한글"], []], scripts[1:])
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            permissions = project_type_detection.detect_project_permissions(self.project)
            reference = doctor.inspect_project_health(self.project)
        self.assertEqual(len(set(permissions)), len(permissions))
        self.assertIn("Bash(yarn install)", permissions)
        self.assertNotIn("Bash(npm run ignored)", permissions)
        self.assertEqual({"count": len(permissions)}, self.check("doctor-permission-count", payload))

        with patch.dict(os.environ, self.env, clear=True), patch.object(
            project_type_detection, "_find_package_jsons", side_effect=AssertionError("Python scanned Node"),
        ):
            self.assertEqual(permissions, project_type_detection.detect_project_permissions(
                self.project, native_node_scan=True,
            ))
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            doctor, "detect_project_permissions", side_effect=AssertionError("Python expanded permissions"),
        ):
            self.assertEqual(reference, doctor.inspect_project_health(self.project))

        (self.project / "empty" / "package.json").write_text('{"scripts":null}')
        self.assertEqual(125, self.raw("doctor-node-manifests", payload).returncode)
        self.assertEqual(125, self.raw("doctor-permission-count", payload).returncode)
        self.assertEqual(125, self.raw("doctor-project-facts", payload).returncode)
        for backend in ("python", "auto"):
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True):
                with self.assertRaisesRegex(TypeError, "not iterable"):
                    doctor.inspect_project_health(self.project)

    def test_doctor_permission_markers_match_legacy_commands(self):
        payload = {"project": str(self.project)}
        self.assertEqual({"count": 0}, self.check("doctor-permission-count", payload))
        (self.project / "package.json").write_text("{}")
        self.assertEqual({"count": 18}, self.check("doctor-permission-count", payload))
        for name in ("Package.swift", "Cargo.toml", "go.mod"):
            (self.project / name).touch()
        module = self.project / "modules" / "client"
        module.mkdir(parents=True)
        (module / "build.gradle.kts").touch()
        scripts = self.project / "scripts"
        scripts.mkdir()
        (scripts / ".tool.py").touch()

        markers = self.check("doctor-permission-markers", payload)
        self.assertEqual({
            "swift": True, "gradle": True, "rust": True, "go": True,
            "python_packaged": False, "python_scripts": True,
        }, markers)
        for packaged in (False, True):
            if packaged:
                (self.project / "pyproject.toml").touch()
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                reference = doctor.inspect_project_health(self.project)
            self.assertEqual({"count": reference["detected_permission_count"]},
                             self.check("doctor-permission-count", payload))
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                doctor, "detect_project_permissions", side_effect=AssertionError("Python expanded permissions"),
            ):
                self.assertEqual(reference, doctor.inspect_project_health(self.project))

    def test_doctor_permission_markers_preserve_depth_and_symlink_fallback(self):
        nested = self.project / "outer" / "deep"
        nested.mkdir(parents=True)
        (nested / "ignored.py").touch()
        (nested / "build.gradle").touch()
        hidden = self.project / ".hidden"
        hidden.mkdir()
        (hidden / "ignored.py").touch()
        external = self.base / "external"
        external.mkdir()
        (external / "linked.py").touch()
        (external / "build.gradle.kts").touch()
        (self.project / ".linked").symlink_to(external, target_is_directory=True)
        payload = {"project": str(self.project)}
        markers = self.check("doctor-permission-markers", payload)
        self.assertFalse(markers["gradle"])
        self.assertFalse(markers["python_scripts"])

        (self.project / "linked").symlink_to(external, target_is_directory=True)
        self.assertEqual(125, self.raw("doctor-permission-markers", payload).returncode)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(
                ["Edit(**/*.py)"],
                project_type_detection.detect_project_permissions(self.project, native_markers=True),
            )

    def test_doctor_launcher_health_keeps_warning_order_and_uses_verified_binary(self):
        rules = Path(self.env["MORU_HOME"])
        pointer = self.entry.parent.parent / "moru-root"
        text = self.entry.read_bytes()
        pointer_text = pointer.read_bytes()
        self.entry.write_bytes(text.replace(b"\n", b"\r\n"))
        pointer.write_bytes(pointer_text.replace(b"\n", b"\r\n"))

        def compare(expected):
            with patch.dict(os.environ, self.env, clear=True):
                reference = stable_launcher.stable_launcher_issue(rules)
                self.assertEqual(expected, reference.partition(" is missing")[0])
                with patch.object(
                    stable_launcher, "_read_text", side_effect=AssertionError("Python re-read"),
                ):
                    actual = doctor.inspect_project_health(self.project)
                self.assertEqual(reference, actual["launchers"]["launcher_issue"])

        compare("")
        pointer.write_bytes(pointer_text + b"\n")
        compare("Moru Core root pointer")
        self.entry.chmod(0o644)
        compare("Moru Core stable launcher")
        self.entry.chmod(0o755)

        # A diagnostic should never execute the installed binary it is checking.
        binary = self.entry.with_name("moru-hook-native")
        ran = self.base / "unchecked-binary-ran"
        binary.write_text(f"#!/bin/sh\n: > {shlex.quote(str(ran))}\nexit 1\n")
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            stable_launcher, "_read_text", side_effect=AssertionError("Python re-read"),
        ):
            self.assertIn("stable launcher is missing or stale",
                          stable_launcher.stable_launcher_issue(rules, native_check=True))
        self.assertFalse(ran.exists())

    def test_doctor_rust_report_preserves_cli_formats_and_recommendation_order(self):
        agents = self.project / "AGENTS.md"

        def cli(format_name, backend):
            output = io.StringIO()
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend}, clear=True), patch(
                "sys.stdout", output,
            ):
                code = doctor.main(["--project", str(self.project), "--format", format_name])
            return code, output.getvalue()

        for healthy in (False, True):
            with self.subTest(healthy=healthy):
                if not healthy:
                    agents.unlink()
                else:
                    agents.write_text(f"{doctor.MANAGED_BEGIN}\n{doctor.MANAGED_END}\n")
                warning = "" if healthy else 'Launcher not ready — 상태 🛠\u2028" \\ \t\n\x00\x7f'
                counts = {"active_records": 1, "expired_or_due": 0 if healthy else 2, "unreadable": 0}
                with patch.object(doctor, "stable_launcher_issue", return_value=warning), patch.object(
                    doctor, "_project_memory_stats", return_value=counts,
                ):
                    json_reference = cli("json", "python")
                    markdown_reference = cli("markdown", "python")
                    with patch.object(
                        doctor, "_assemble_report_python", side_effect=AssertionError("Python fallback"),
                    ), patch.object(
                        doctor, "_render_markdown_doctor", side_effect=AssertionError("Python rendering"),
                    ), patch.object(doctor, "json", wraps=json) as python_json:
                        python_json.dumps.side_effect = AssertionError("Python JSON encoding")
                        self.assertEqual(json_reference, cli("json", "auto"))
                        self.assertEqual(markdown_reference, cli("markdown", "auto"))
                report = json.loads(json_reference[1])
                if healthy:
                    self.assertEqual([], report["recommendations"])
                    self.assertIn("- recommendations: none (healthy)\n", markdown_reference[1])
                else:
                    first, second, third = report["recommendations"]
                    self.assertEqual(warning, first)
                    self.assertTrue(second.startswith("No AGENTS.md;"))
                    self.assertTrue(third.startswith("Project memory has 2 record(s)"))

        native_request = NativeProbe.request

        def decline_project_facts(protocol, operation, data, **kwargs):
            if operation == "doctor-project-facts":
                return None
            return native_request(protocol, operation, data, **kwargs)

        with patch.object(doctor, "_active_run_count", return_value=1e-7), patch.object(
            NativeProbe, "request", side_effect=decline_project_facts,
        ):
            reference = cli("json", "python")
            with patch.object(doctor, "json", wraps=json) as python_json:
                self.assertEqual(reference, cli("json", "auto"))
                python_json.dumps.assert_called_once()
        self.assertIn('"active_runs": 1e-07', reference[1])

    def test_doctor_memory_counts_validated_rows_without_python_body_transport(self):
        today = date(2026, 11, 23)
        with patch.dict(os.environ, self.env, clear=True):
            directory = project_memory.store_dir(self.project)
        directory.mkdir(parents=True)
        rows = (
            ("active", "2026-11-22"), ("approved", "2026-11-23"),
            ("pending", "2026-11-24"), ("retired", "2026-11-21"),
        )
        for number, (status, review_on) in enumerate(rows, start=1):
            record = {
                "schema_version": 1, "id": f"{number:016x}", "scope": "all",
                "body": f"Local note {number}", "source": "Fixture",
                "status": status, "review_on": review_on,
            }
            record["digest"] = project_memory._digest(record)
            (directory / f"{record['id']}.json").write_text(json.dumps(record))
        (directory / "broken.json").write_text("{")
        payload = {
            "path": str(directory), "today": today.isoformat(),
            "unicode": unicodedata.unidata_version,
            "statuses": sorted(project_memory.RECALLABLE_STATUSES),
        }
        expected = {"active_records": 4, "expired_or_due": 2, "unreadable": 1}
        self.assertEqual(expected, self.check("doctor-memory", payload))
        with patch.object(doctor, "date") as clock:
            clock.today.return_value = today
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                reference = doctor.inspect_project_health(self.project)
            self.assertEqual(expected, reference["state"]["project_memory"])
            with patch.dict(os.environ, self.env, clear=True), patch.object(
                doctor, "project_memory_scan", side_effect=AssertionError("Python scan ran"),
            ), patch.object(
                doctor, "project_memory_findings", side_effect=AssertionError("Python findings ran"),
            ):
                self.assertEqual(reference, doctor.inspect_project_health(self.project))

    def test_capsule_binding_matches_python_and_preserves_legacy_fallback(self):
        docs = [{"\U00010000": "😀", "\uffff": "한글\x7f\n\u2028", "a": [True, 0, 2**64 - 1, -2**63]}]
        snapshot = {"required_docs": docs, "schema_version": True,
                    "request_fingerprint": "request", "route_fingerprint": "route"}
        capsule = {**snapshot, "schema_version": 4, "phase": "ready",
                   "preflight_evidence": {"sha256": "hash", "filename": "preflight.json"},
                   "reuse_policy": {"gate_effect": "none"}}
        for kind, record, binding in (
            ("preflight", snapshot, capsule_state.preflight_snapshot_binding_fingerprint),
            ("capsule", capsule, capsule_state.execution_capsule_binding_fingerprint),
        ):
            with self.subTest(kind=kind):
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = binding(record)
                self.assertEqual({"sha256": expected}, self.check("capsule-binding", {
                    "kind": kind, "record": {**record, "unbound": "ignored"},
                }))
                with patch.dict(os.environ, self.env, clear=True), patch.object(capsule_state, "json") as encoder:
                    encoder.dumps.side_effect = AssertionError("unexpected Python serialization")
                    self.assertEqual(expected, binding({**record, "unbound": object()}))

                for value in (2**64, -2**63 - 1, -0.0, float("nan"), "\ud800", {0: "legacy"}):
                    with self.subTest(value=repr(value)):
                        legacy = {**record, "required_docs": [value]}
                        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                            original = binding(legacy)
                        with patch.dict(os.environ, self.env, clear=True), patch.object(
                            capsule_state, "json", wraps=json
                        ) as encoder:
                            self.assertEqual(original, binding(legacy))
                            encoder.dumps.assert_called_once()
        for kind, record in (("capsule", {**capsule, "phase": "preflight"}),
                             ("preflight", {**snapshot, "schema_version": 2})):
            result = self.raw("capsule-binding", {"kind": kind, "record": record})
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

    def test_capsule_shape_preserves_first_failure_and_legacy_inputs(self):
        digest = "a" * 64
        snapshot = {"schema_version": True, "route_fingerprint": digest, "request_fingerprint": digest,
                    "required_docs": [{"path": "문서", "size_bytes": False, "sha256": digest}]}
        git_state = {"head": "head", "worktree_fingerprint": digest, "worktree_signature": digest}
        capsule = {**snapshot, "schema_version": 4, "phase": "ready", "created_at": "time",
                   "preflight_evidence": {"filename": "..", "sha256": digest},
                   "project_git": git_state, "rules_git": git_state,
                   "reuse_policy": dict(reversed(list(capsule_state.REUSE_POLICY.items())))}
        capsule_cases = [
            {},
            {"invalid_json": [False], "schema_version": 0},
            {**capsule, "invalid_json": [], "schema_version": 0},
            {**capsule, "extra": True, "phase": []},
            {**capsule, "phase": "invalid", "created_at": ""},
            {**capsule, "created_at": "", "route_fingerprint": ""},
            {**capsule, "route_fingerprint": "", "request_fingerprint": ""},
            {**capsule, "request_fingerprint": "", "preflight_evidence": {}},
            {**capsule, "rules_git": {}, "reuse_policy": {}},
            {**capsule, "reuse_policy": {}, "required_docs": None},
            {**capsule, "required_docs": {}, "gate_ledger": None},
            {**capsule, "gate_ledger": None},
            {**capsule, "phase": "preflight"},
            capsule,
        ]
        for filename in (".", "..", "file/", "a/file", "a\\file", "\0"):
            capsule_cases.append({**capsule, "preflight_evidence": {"filename": filename, "sha256": digest}})
        snapshot_cases = [
            [], {}, {**snapshot, "extra": True}, {**snapshot, "schema_version": False},
            {**snapshot, "route_fingerprint": "A" * 64, "request_fingerprint": ""},
            {**snapshot, "request_fingerprint": "", "required_docs": None},
            {**snapshot, "required_docs": [{"path": "doc", "size_bytes": -1, "sha256": digest}]},
            snapshot,
        ]
        for kind, valid, cases, validator in (
            ("capsule", capsule, capsule_cases, capsule_validation._shape_failures),
            ("preflight", snapshot, snapshot_cases, capsule_validation._preflight_snapshot_shape_failures),
        ):
            for record in cases:
                with self.subTest(kind=kind, record=record):
                    with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                        expected = validator(record)
                    self.assertEqual({"failures": expected}, self.check("capsule-shape", {
                        "kind": kind, "record": record,
                    }))
            with patch.dict(os.environ, self.env, clear=True):
                with patch.object(capsule_validation, "_is_doc", side_effect=AssertionError("Python fallback")):
                    self.assertEqual([], validator(valid))
                legacy = {**capsule, "schema_version": 4.0} if kind == "capsule" else {
                    **snapshot, "required_docs": [{"path": "doc", "size_bytes": 2**80, "sha256": digest}],
                }
                self.assertEqual([], validator(legacy))
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(TypeError):
            capsule_validation._shape_failures({**capsule, "phase": []})

    def test_capsule_parent_ledger_preserves_observed_identity_and_error_order(self):
        evidence = self.project / "사전검증.json"
        evidence.write_text("{}", encoding="utf-8")
        alias = self.project / "parent.json"
        alias.symlink_to(evidence)
        ledger_path = self.project / "gate-evidence.json"
        route = {"command": "refactor", "local_delivery_contract": "staged_v1"}
        good = {"gate": "request intake", "status": "SUCCESS", "evidence": "seen"}
        blank = {**good, "evidence": "\x1c\u00a0\u3000"}
        zero_width = {**good, "evidence": "\u200b"}
        base = {
            "schema_version": True,
            "preflight_evidence": str(alias),
            "preflight_evidence_sha256": preflight_evidence_sha256(evidence),
            "route_fingerprint": route_fingerprint(route),
            "entries": [good],
        }
        cases = [
            {},
            {"entries": [blank, zero_width]},
            {"entries": [good, {"gate": "request intake", "status": "FAIL"}]},
            {"entries": [blank, {**good, "evidence": True}]},
            {"entries": [good, None]},
            {"schema_version": 2, "preflight_evidence": "wrong", "preflight_evidence_sha256": None,
             "route_fingerprint": "wrong", "entries": "wrong"},
        ]
        original_probe = capsule_bindings.native_capsule_probe
        for overrides in cases:
            with self.subTest(overrides=overrides):
                ledger_path.write_text(json.dumps({**base, **overrides}), encoding="utf-8")
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = capsule_bindings.gate_ledger_failures(ledger_path, evidence, route)
                results = []

                def observe(operation, request):
                    result = original_probe(operation, request)
                    results.append(result)
                    return result

                with patch.dict(os.environ, self.env, clear=True), patch.object(
                    capsule_bindings, "native_capsule_probe", side_effect=observe
                ):
                    self.assertEqual(expected, capsule_bindings.gate_ledger_failures(ledger_path, evidence, route))
                    self.assertEqual([{"failures": expected}], results)
        with patch.dict(os.environ, self.env, clear=True):
            ledger_path.write_text(json.dumps({**base, "schema_version": 1.0}), encoding="utf-8")
            self.assertEqual([], capsule_bindings.gate_ledger_failures(ledger_path, evidence, route))
            ledger_path.write_text("{not json", encoding="utf-8")
            self.assertEqual(["execution capsule parent gate ledger is not valid JSON"],
                             capsule_bindings.gate_ledger_failures(ledger_path, evidence, route))

    def test_native_preflight_route_and_request_digests_match_python(self):
        routes = [
            {},
            {"command": "리팩터링", "platform": False, "concerns": 0, "docs": "",
             "reference_docs": None, "gates": ["🐈"], "local_delivery_contract": "staged_v1",
             "lifecycle_version": None, "project_memory_contract": {"z": 2**80, "a": "\x7f"}},
            {"organization": {"id": "팀", "commit": "c", "required_docs": [
                {"path": "문서", "sha256": "f", "ignored": 1}, {"path": "🐈"}, {"sha256": "g"},
            ]}},
            {"local_delivery_contract": None},
        ]
        for route in routes:
            for intake in ({}, {"request": "경로\0🐈", "continuation_scope": False, "request_classified": [False],
                                "classification_evidence": "e\x7f"}):
                with self.subTest(route=route, intake=intake):
                    with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                        expected = capsule.create_preflight_snapshot(self.project, route, intake)
                    response = self.check("capsule-identities", {"route": route, "intake": intake})
                    self.assertEqual(response, {key: expected[key] for key in response})
                    with patch.dict(os.environ, self.env, clear=True), patch.multiple(
                        capsule,
                        route_fingerprint=Mock(side_effect=AssertionError("Python route")),
                        request_fingerprint=Mock(side_effect=AssertionError("Python request")),
                    ):
                        self.assertEqual(expected, capsule.create_preflight_snapshot(self.project, route, intake))
        legacy = {"request": ["coerced"], "request_classified": True}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = capsule.create_preflight_snapshot(self.project, {}, legacy)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(expected, capsule.create_preflight_snapshot(self.project, {}, legacy))
        declined = self.raw("capsule-identities", {"route": {}, "intake": legacy})
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))

    def test_capsule_persistence_uses_private_atomic_replacement_and_safe_fallback(self):
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        evidence = run / "preflight.json"
        evidence.write_text("{}", encoding="utf-8")
        destination = run / "execution-capsule.json"
        destination.write_bytes(b"previous")
        destination.chmod(0o644)
        payload = {"z": ["문서\x7f🐈", 2**64 - 1], "a": {"done": True}}
        expected = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            capsule_state, "_encoded_json", side_effect=AssertionError("unexpected Python write")
        ):
            capsule._write_execution_capsule(destination, payload)
        self.assertEqual(expected, destination.read_bytes())
        self.assertEqual(0o600, destination.stat().st_mode & 0o777)
        self.assertEqual([], list(run.glob("*.tmp")))

        suffix = "b" * 32
        collision = run / f"{destination.name}.{suffix}.tmp"
        collision.write_bytes(b"other producer")
        request = {"path": str(destination), "temporary": suffix, "record": payload}
        self.assertEqual({"errno": errno.EEXIST}, self.check("capsule-replace", request))
        self.assertEqual(b"other producer", collision.read_bytes())
        self.assertEqual(expected, destination.read_bytes())
        for unsafe in (
            {**request, "path": str(run / "continuation.json")},
            {**request, "record": {"storage": "project_local_never_sync"}},
            {**request, "temporary": "../escape"},
        ):
            result = self.raw("capsule-replace", unsafe)
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

        with patch.dict(os.environ, self.env, clear=True):
            legacy = {"wide": 2**80, "float": 0.5}
            capsule._write_execution_capsule(destination, legacy)
            self.assertEqual(legacy, json.loads(destination.read_bytes()))
            custom = self.project / "custom" / "capsule.json"
            capsule._write_execution_capsule(custom, payload)
            self.assertEqual(expected, custom.read_bytes())
            with patch("support.native_probe_transport.subprocess.run", side_effect=subprocess.TimeoutExpired("native", 10)):
                with self.assertRaisesRegex(OSError, "replacement outcome could not be determined"):
                    capsule._write_execution_capsule(destination, payload)
            self.assertEqual(legacy, json.loads(destination.read_bytes()))

    def test_capsule_read_is_bounded_and_preserves_python_read_outcomes(self):
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        path = run / "execution-capsule.json"
        request = {"path": str(path)}
        self.assertEqual({"record": {}}, self.check("capsule-read", request))

        record = {"z": True, "a": "문서🐈", "count": 2**64 - 1}
        path.write_bytes(br'{"z":false,"a":"\ud55c","z":true,"count":18446744073709551615}')
        loaded = self.check("capsule-read", request)["record"]
        self.assertEqual({**record, "a": "한"}, loaded)
        self.assertEqual(list(record), list(loaded))
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            capsule, "read_json_object", side_effect=AssertionError("unexpected Python read")
        ):
            self.assertEqual(loaded, capsule.read_execution_capsule(path))

        path.write_bytes(b"null")
        self.assertEqual({"record": {"invalid_json": True}}, self.check("capsule-read", request))
        for raw in (b"{broken", b'{"wide":18446744073709551616}', b'{"fraction":0.5}',
                    br'{"s":"\ud800"}', b'{"long":"' + b"x" * (256 * 1024) + b'"}'):
            with self.subTest(prefix=raw[:24]):
                path.write_bytes(raw)
                declined = self.raw("capsule-read", request)
                self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
                with patch.dict(os.environ, self.env, clear=True):
                    self.assertEqual(capsule.read_json_object(path), capsule.read_execution_capsule(path))
        path.write_bytes(b'{"duplicate":' + b"9" * 650 + b',"duplicate":1}')
        declined = self.raw("capsule-read", request)
        self.assertEqual(125, declined.returncode)
        path.write_bytes(b'{"s":"\xff"}')
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(UnicodeDecodeError):
            capsule.read_execution_capsule(path)

        alternate = run / "alias-target.json"
        alternate.write_text(json.dumps(record), encoding="utf-8")
        path.unlink()
        path.symlink_to(alternate)
        declined = self.raw("capsule-read", request)
        self.assertEqual(125, declined.returncode)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(record, capsule.read_execution_capsule(path))

    def test_capsule_refresh_assembles_and_persists_native_phase_without_replay(self):
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        evidence = run / "preflight.json"
        route = {"command": "refactor"}
        evidence.write_text(json.dumps({"route": route, "request_intake": {"request": "검증"}}))
        ledger = run / "gate-evidence.json"
        ledger.write_bytes(b'{"evidence":"\xed\x95\x9c"}\r\n')
        output = run / "execution-capsule.json"
        digest = "a" * 64
        git_state = {"head": "head", "worktree_fingerprint": digest, "worktree_signature": digest}
        for docs, failures, phase in (([], [], "ready"), (None, [], "preflight"),
                                      ([], ["not ready"], "preflight")):
            with self.subTest(docs=docs, failures=failures), patch.multiple(
                capsule,
                git_states_for_paths=Mock(return_value=(git_state, git_state)),
                current_required_docs=Mock(return_value=docs),
                gate_ledger_failures=Mock(return_value=failures),
            ):
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    reference = capsule.refresh_execution_capsule(self.project, self.project, evidence, route)
                self.assertEqual(phase, reference["phase"])
                with patch.dict(os.environ, self.env, clear=True), patch.multiple(
                    capsule,
                    _write_execution_capsule=Mock(side_effect=AssertionError("unexpected separate write")),
                    file_hash_record=Mock(side_effect=AssertionError("unexpected Python file hash")),
                ):
                    actual = capsule.refresh_execution_capsule(self.project, self.project, evidence, route)
                self.assertEqual({**reference, "created_at": actual["created_at"]}, actual)
                self.assertEqual(list(reference), list(actual))
                self.assertEqual((json.dumps(actual, indent=2, sort_keys=True) + "\n").encode(), output.read_bytes())
                self.assertEqual(0o600, output.stat().st_mode & 0o777)
                with patch.dict(os.environ, self.env, clear=True), patch(
                    "support.native_probe_transport.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("native", 10),
                ), self.assertRaisesRegex(OSError, "refresh outcome could not be determined"):
                    capsule.refresh_execution_capsule(self.project, self.project, evidence, route)
                self.assertEqual(actual, json.loads(output.read_bytes()))

        with patch.dict(os.environ, self.env, clear=True), patch.multiple(
            capsule,
            git_states_for_paths=Mock(return_value=(git_state, git_state)),
            current_required_docs=Mock(return_value=[]),
            gate_ledger_failures=Mock(return_value=["ledger missing"]),
            file_hash_record=Mock(side_effect=AssertionError("unexpected Python file hash")),
        ):
            ledger.unlink()
            without_ledger = capsule.refresh_execution_capsule(self.project, self.project, evidence, route)
            self.assertNotIn("gate_ledger", without_ledger)
            self.assertEqual("preflight", without_ledger["phase"])

        previous = output.read_bytes()
        evidence.unlink()
        declined = self.raw("capsule-refresh", {
            "path": str(output), "temporary": "b" * 32, "ledger_valid": False,
            "observed": {"required_docs": []},
        })
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        self.assertEqual(previous, output.read_bytes())
        self.assertEqual([], list(run.glob("*.tmp")))

    def test_capsule_directory_state_matches_python_and_reuses_only_current_signature(self):
        root = self.base / "디렉터리"
        root.mkdir()
        for name in ("local", ".moru", "nested", "nested/local"):
            (root / name).mkdir()
        (root / "local" / "ignored").write_text("root local")
        (root / ".moru" / "ignored").write_text("runtime")
        (root / "nested" / "local" / "included").write_text("nested local")
        (root / "ignored.log").write_text("ignored")
        (root / ".log").write_text("dotfile")
        file = root / "자료🐈"
        file.write_bytes(b"before\0\xff")
        file.chmod(0o751)
        (root / "link.log").symlink_to("missing")

        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = directory_fingerprint.directory_state(root)
        self.assertEqual({"state": expected}, self.check("capsule-directory", {"path": str(root)}))
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            directory_fingerprint, "directory_signature", side_effect=AssertionError("unexpected Python scan")
        ):
            self.assertEqual(expected, directory_fingerprint.directory_state(root))
            record = {**expected, "retained_field": "legacy"}
            self.assertEqual(record, directory_fingerprint.directory_state(root, record))
            (root / "ignored.log").write_text("ignored change")
            self.assertEqual(record, directory_fingerprint.directory_state(root, record))
            file.write_bytes(b"changed\0\xff")
            changed = directory_fingerprint.directory_state(root, record)
        self.assertNotEqual(expected["worktree_signature"], changed["worktree_signature"])
        self.assertNotEqual(expected["worktree_fingerprint"], changed["worktree_fingerprint"])
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            self.assertEqual(directory_fingerprint.directory_state(root), changed)
        with (root / "oversized").open("wb") as stream:
            stream.truncate(directory_fingerprint.MAX_DIRECTORY_BYTES + 1)
        declined = self.raw("capsule-directory", {"path": str(root)})
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        with patch.dict(os.environ, self.env, clear=True), self.assertRaisesRegex(
            RuntimeError, "untracked byte size exceeds execution-capsule limit"
        ):
            directory_fingerprint.directory_state(root)

    def test_capsule_worktree_signature_matches_raw_git_status_reference(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.project), *args],
                           env=self.env, capture_output=True, check=True, timeout=8)

        old = self.project / "old\n이름.txt"
        changed = self.project / "partial.txt"
        removed = self.project / "removed"
        for path in (old, changed, removed):
            path.write_text("base\n")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "base")
        renamed = self.project / "new\t이름.txt"
        git("mv", old.name, renamed.name)
        changed.write_bytes(b"staged\0")
        git("add", changed.name)
        changed.write_bytes(b"unstaged\0\xff")
        removed.unlink()
        (self.project / "link").symlink_to("missing")
        (self.project / "🐈").write_bytes(b"untracked\0")

        request = {"path": str(self.project), "max_files": 5_000, "max_bytes": 256 * 1024 * 1024}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = worktree_fingerprint.worktree_signature(self.project)
            reference = worktree_fingerprint.capture_worktree_state(self.project)
        index = self.project / ".git/index"
        index_before = index.read_bytes()
        raw = self.raw("capsule-worktree-signature", request, PATH=self.env["PATH"])
        self.assertEqual(0, raw.returncode, raw.stderr)
        self.assertEqual({"signature": expected}, json.loads(raw.stdout)["result"])
        raw = self.raw("capsule-worktree-signature", {**request, "strong": True}, PATH=self.env["PATH"])
        self.assertEqual(0, raw.returncode, raw.stderr)
        self.assertEqual(reference._asdict(), json.loads(raw.stdout)["result"])
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            worktree_fingerprint, "_capture_status", side_effect=AssertionError("unexpected Python scan")
        ):
            self.assertEqual(expected, worktree_fingerprint.worktree_signature(self.project))
            self.assertEqual(reference, worktree_fingerprint.capture_worktree_state(self.project))
        self.assertEqual(index_before, index.read_bytes())
        declined = self.raw("capsule-worktree-signature", {**request, "max_files": 0}, PATH=self.env["PATH"])
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        for excluded in (old.name, renamed.name, changed.name, "🐈", "*.txt", "not-present"):
            with self.subTest(excluded=excluded):
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    python = worktree_fingerprint.worktree_fingerprint_excluding_path(self.project, excluded)
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                    worktree_fingerprint, "_capture_status", side_effect=AssertionError("unexpected Python scan")
                ):
                    self.assertEqual(python, worktree_fingerprint.worktree_fingerprint_excluding_path(
                        self.project, excluded
                    ))
        self.assertEqual(index_before, index.read_bytes())

    def test_capsule_native_worktree_fingerprint_handles_unborn_head(self):
        file = self.project / "new.bin"
        file.write_bytes(b"staged\0")
        subprocess.run(["git", "-C", str(self.project), "add", file.name],
                       env=self.env, capture_output=True, check=True, timeout=8)
        file.write_bytes(b"unstaged\0\xff")
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = worktree_fingerprint.capture_worktree_state(self.project)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            worktree_fingerprint, "_capture_status", side_effect=AssertionError("unexpected Python scan")
        ):
            self.assertEqual(expected, worktree_fingerprint.capture_worktree_state(self.project))

    def test_capsule_check_cli_runs_matching_git_case_without_python(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.project), *args],
                           env=self.env, capture_output=True, check=True, timeout=8)

        (self.project / ".gitignore").write_text(".moru/\n")
        doc = self.project / "문서.md"
        doc.write_text("required\n")
        git("add", ".gitignore", doc.name)
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "base")
        untracked = self.project / "untracked.txt"
        untracked.write_text("original\n")
        call = self.capsule_check_runner(self.project, self.project, doc.name)

        reference = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        self.assertEqual(reference, call(PATH=str(self.empty)))

        metadata = untracked.stat()
        os.utime(untracked, ns=(metadata.st_atime_ns, metadata.st_mtime_ns - 60_000_000_000))
        self.assertEqual(reference, call(MORU_LAUNCHER_BACKEND="python"))
        self.assertEqual(reference, call(PATH=str(self.empty)))

        untracked.write_text("modified\n")
        changed = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(1, changed[0], changed)
        self.assertIn(b"execution capsule project worktree status changed", changed[1])
        self.assertEqual(changed, call())
        self.assertEqual(127, call(PATH=str(self.empty))[0])
        untracked.write_text("original\n")

        doc.write_text("changed\n")
        refused = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(1, refused[0], refused)
        self.assertIn(b"execution capsule required doc hash changed", refused[1])
        self.assertEqual(refused, call())
        self.assertEqual(127, call(PATH=str(self.empty))[0])

    def test_capsule_check_cli_validates_non_git_roots_without_python(self):
        project = self.base / "plain-parent" / "plain-project"
        rules = self.base / "plain-rules"
        project.mkdir(parents=True)
        rules.mkdir()
        required = rules / "문서.md"
        required.write_text("required\n")
        content = project / "data.txt"
        content.write_text("original\n")
        call = self.capsule_check_runner(project, rules, required.name)

        reference = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        self.assertEqual(reference, call(PATH=str(self.empty)))

        metadata = content.stat()
        os.utime(content, ns=(metadata.st_atime_ns, metadata.st_mtime_ns - 60_000_000_000))
        self.assertEqual(reference, call(PATH=str(self.empty)))

        content.write_text("modified\n")
        changed = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(1, changed[0], changed)
        self.assertIn(b"execution capsule project worktree status changed", changed[1])
        self.assertEqual(changed, call())
        self.assertEqual(127, call(PATH=str(self.empty))[0])
        content.write_text("original\n")

        (project.parent / ".git").mkdir()
        unavailable = call(MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(1, unavailable[0], unavailable)
        self.assertIn(b"execution capsule project/rules git state is unavailable", unavailable[1])
        self.assertEqual(unavailable, call())
        self.assertEqual(127, call(PATH=str(self.empty))[0])

    def test_capsule_refresh_cli_writes_matching_ready_record_without_python(self):
        doc = self.commit_capsule_rules()
        call = self.capsule_check_runner(self.project, self.project, doc.name)
        run = self.project / ".moru" / "runs" / ("a" * 32)
        target = run / "execution-capsule.json"
        ledger = run / "gate-evidence.json"
        original_ledger = ledger.read_bytes()

        reference = call(action="refresh", MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        expected = json.loads(target.read_bytes())
        target.unlink()
        self.assertEqual(reference, call(action="refresh", PATH=str(self.empty)))
        native = json.loads(target.read_bytes())
        self.assertTrue(native.pop("created_at").endswith("+00:00"))
        expected.pop("created_at")
        self.assertEqual(expected, native)
        self.assertEqual(0o600, target.stat().st_mode & 0o777)
        self.assertEqual(original_ledger, ledger.read_bytes())
        self.assertEqual(0, call(PATH=str(self.empty))[0])

    def test_capsule_refresh_cli_writes_preflight_for_missing_or_invalid_ledger(self):
        doc = self.commit_capsule_rules()
        call = self.capsule_check_runner(self.project, self.project, doc.name)
        run = self.project / ".moru" / "runs" / ("a" * 32)
        target = run / "execution-capsule.json"
        ledger = run / "gate-evidence.json"
        invalid_schema = {**json.loads(ledger.read_bytes()), "schema_version": 0}
        for value in (None, {}, invalid_schema):
            with self.subTest(ledger=value):
                if value is None:
                    ledger.unlink()
                else:
                    ledger.write_text(json.dumps(value))
                reference = call(action="refresh", MORU_LAUNCHER_BACKEND="python")
                self.assertEqual(0, reference[0], reference)
                self.assertEqual("preflight", json.loads(reference[1])["phase"])
                expected = json.loads(target.read_bytes())
                self.assertEqual(value is not None, "gate_ledger" in expected)
                self.assertEqual(reference, call(action="refresh", PATH=str(self.empty)))
                native = json.loads(target.read_bytes())
                native.pop("created_at")
                expected.pop("created_at")
                self.assertEqual(expected, native)

        previous = target.read_bytes()
        ledger.write_text("{")
        self.assertEqual(127, call(action="refresh", PATH=str(self.empty))[0])
        self.assertEqual(previous, target.read_bytes())
        self.assertEqual("preflight", json.loads(call(action="refresh")[1])["phase"])

    def test_capsule_refresh_does_not_write_if_missing_ledger_appears(self):
        doc = self.commit_capsule_rules()
        call = self.capsule_check_runner(self.project, self.project, doc.name)
        run = self.project / ".moru" / "runs" / ("a" * 32)
        target = run / "execution-capsule.json"
        ledger = run / "gate-evidence.json"
        incoming = ledger.with_suffix(".incoming")
        original_ledger = ledger.read_bytes()
        previous = target.read_bytes()
        ledger.rename(incoming)

        # Inject the missing ledger during the first Git read after initial evidence observation.
        shim_dir = self.base / "git-shim"
        shim_dir.mkdir()
        git = shim_dir / "git"
        source, destination = (shlex.quote(str(path)) for path in (incoming, ledger))
        real_git = shlex.quote(shutil.which("git"))
        git.write_text(f"#!/bin/sh\nif [ -f {source} ]; then /bin/mv {source} {destination}; fi\n"
                       f'exec {real_git} "$@"\n')
        git.chmod(0o700)
        self.assertEqual(127, call(action="refresh", PATH=str(shim_dir))[0])
        self.assertEqual(original_ledger, ledger.read_bytes())
        self.assertEqual(previous, target.read_bytes())

    def test_capsule_refresh_cli_writes_ready_directory_and_mixed_records_without_python(self):
        git_doc = self.commit_capsule_rules()
        plain_rules = self.base / "rules-parent" / "plain-rules"
        plain_rules.mkdir(parents=True)
        plain_doc = plain_rules / git_doc.name
        plain_doc.write_text("required\n")
        plain_project = self.base / "plain" / "project"
        mixed_project = self.base / "mixed" / "project"
        for project in (plain_project, mixed_project):
            project.mkdir(parents=True)
            (project / "content.txt").write_text("data\n")
        for name, project, required, directory in (
            ("plain", plain_project, plain_doc, plain_project),
            ("git-rules", mixed_project, git_doc, mixed_project),
            ("git-project", self.project, plain_doc, plain_rules),
        ):
            with self.subTest(roots=name):
                call = self.capsule_check_runner(project, required.parent, required.name)
                run = project / ".moru" / "runs" / ("a" * 32)
                target = run / "execution-capsule.json"
                reference = call(action="refresh", MORU_LAUNCHER_BACKEND="python")
                self.assertEqual(0, reference[0], reference)
                expected = json.loads(target.read_bytes())
                self.assertEqual(name != "git-project",
                                 expected["project_git"]["head"] == "non-git-directory-v1")
                self.assertEqual(name != "git-rules",
                                 expected["rules_git"]["head"] == "non-git-directory-v1")

                self.assertEqual(reference, call(action="refresh", PATH=str(self.empty)))
                native = json.loads(target.read_bytes())
                native.pop("created_at")
                expected.pop("created_at")
                self.assertEqual(expected, native)
                self.assertEqual(0, call(PATH=str(self.empty))[0])

                previous = target.read_bytes()
                (directory.parent / ".git").mkdir()
                self.assertEqual(127, call(action="refresh", PATH=str(self.empty))[0])
                self.assertEqual(previous, target.read_bytes())

    def commit_capsule_rules(self):
        (self.project / ".gitignore").write_text(".moru/\n")
        doc = self.project / "문서.md"
        doc.write_text("required\n")
        subprocess.run(
            ["git", "-C", str(self.project), "add", ".gitignore", doc.name],
            env=self.env, capture_output=True, check=True, timeout=8,
        )
        subprocess.run(
            ["git", "-C", str(self.project), "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.test", "commit", "-m", "base"],
            env=self.env, capture_output=True, check=True, timeout=8,
        )
        return doc

    def test_capsule_refresh_cli_distinguishes_unavailable_docs_from_read_limits(self):
        doc = self.commit_capsule_rules()
        extra = self.project / "extra.md"
        extra.write_text("present\n")
        call = self.capsule_check_runner(self.project, self.project, doc.name, extra.name)
        target = self.project / ".moru" / "runs" / ("a" * 32) / "execution-capsule.json"
        outside = self.base / "outside.md"
        outside.write_text("outside\n")
        extra.unlink()

        for state in ("missing", "directory", "outside"):
            with self.subTest(document=state):
                if state == "directory":
                    extra.mkdir()
                elif state == "outside":
                    extra.symlink_to(outside)
                reference = call(action="refresh", MORU_LAUNCHER_BACKEND="python")
                self.assertEqual(0, reference[0], reference)
                self.assertEqual("preflight", json.loads(reference[1])["phase"])
                expected = json.loads(target.read_bytes())
                self.assertEqual([], expected["required_docs"])
                self.assertIn("gate_ledger", expected)
                self.assertEqual(reference, call(action="refresh", PATH=str(self.empty)))
                native = json.loads(target.read_bytes())
                native.pop("created_at")
                expected.pop("created_at")
                self.assertEqual(expected, native)
                if state == "directory":
                    extra.rmdir()
                elif state == "outside":
                    extra.unlink()

        # A regular file above the native read budget is still a valid document.
        byte_count = 4 * 1024 * 1024 + 1
        extra.write_bytes(b"x" * byte_count)
        previous = target.read_bytes()
        self.assertEqual(127, call(action="refresh", PATH=str(self.empty))[0])
        self.assertEqual(previous, target.read_bytes())
        fallback = call(action="refresh")
        self.assertEqual(0, fallback[0], fallback)
        self.assertEqual("ready", json.loads(fallback[1])["phase"])
        self.assertEqual(byte_count, json.loads(target.read_bytes())["required_docs"][-1]["size_bytes"])

    def test_capsule_cli_accepts_equals_options_and_explicit_standard_paths(self):
        doc = self.commit_capsule_rules()
        call = self.capsule_check_runner(self.project, self.project, doc.name)
        relative = Path(".moru") / "runs" / ("a" * 32)
        run = self.project / relative
        target = run / "execution-capsule.json"
        alias = self.project / ".moru" / "alias = capsule.json"
        alias.symlink_to(target)
        options = ["--project=.", "--rules", ".", f"--evidence={relative / 'preflight.json'}"]
        check_options = [*options, "--capsule", str(alias.relative_to(self.project))]
        reference = call(options=check_options, MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        self.assertEqual(reference, call(options=check_options, PATH=str(self.empty)))

        refresh_options = [f"--output={relative / target.name}", *options]
        target.unlink()
        reference = call(action="refresh", options=refresh_options, MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        expected = json.loads(target.read_bytes())
        target.unlink()
        self.assertEqual(reference, call(action="refresh", options=refresh_options, PATH=str(self.empty)))
        native = json.loads(target.read_bytes())
        expected.pop("created_at")
        native.pop("created_at")
        self.assertEqual(expected, native)

        original = target.read_bytes()
        custom = run / "custom = capsule.json"
        custom_options = [*options, f"--output={custom}"]
        self.assertEqual(127, call(action="refresh", options=custom_options, PATH=str(self.empty))[0])
        self.assertFalse(custom.exists())
        self.assertEqual(original, target.read_bytes())
        self.assertEqual(0, call(action="refresh", options=custom_options)[0])
        self.assertTrue(custom.is_file())
        self.assertEqual(original, target.read_bytes())

        duplicate = [*options, "--project=."]
        reference = call(options=duplicate, MORU_LAUNCHER_BACKEND="python")
        self.assertEqual(0, reference[0], reference)
        self.assertEqual(reference, call(options=duplicate))
        self.assertEqual(127, call(options=duplicate, PATH=str(self.empty))[0])

    def capsule_check_runner(self, project, rules, *required_docs):
        run = project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        evidence = run / "preflight.json"
        route = {"command": "refactor", "required_docs": list(required_docs)}
        preflight = {"project": str(project), "rules": str(rules), "route": route}
        evidence.write_text(json.dumps(preflight))
        ledger = run / "gate-evidence.json"
        ledger.write_text(json.dumps({
            "schema_version": 1, "preflight_evidence": str(evidence),
            "preflight_evidence_sha256": preflight_evidence_sha256(evidence),
            "route_fingerprint": route_fingerprint(route),
            "entries": [{"gate": "request intake", "status": "SUCCESS", "evidence": "seen"}],
        }))
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            refreshed = capsule.refresh_execution_capsule(project, rules, evidence, route)
        self.assertEqual("ready", refreshed["phase"])
        args = ["--evidence", str(evidence),
                "--rules", str(rules), "--project", str(project)]
        git = self.empty / "git"
        if not git.is_symlink():
            git.symlink_to(shutil.which("git"))

        def call(*, action="check", options=None, **env):
            result = subprocess.run(
                [str(self.entry), "execution-capsule", action, *(args if options is None else options)],
                cwd=project,
                env={**self.env, **env}, capture_output=True, timeout=20,
            )
            return result.returncode, result.stdout, result.stderr

        return call

    def test_staged_receipt_hash_matches_python_for_index_and_tree(self):
        index = '100755 ef 0\tz"\\악\x7f\U0001f408\0\0' + '100644 ab 0\ta\tb\n\0'
        tree = '100644 blob ab\ta\tb\n\0' + '100755 blob ef\tz"\\악\x7f\U0001f408\0'
        index += "160000 0123 0\te\u0301\0" + "120000 4567 0\té\0" * 2
        tree += "120000 blob 4567\té\0" * 2 + "160000 commit 0123\te\u0301\0"
        for staged, base in ((index, tree), ("", ""), ("", tree)):
            with self.subTest(empty=not staged):
                expected = (LocalDeliveryProof._identity(staged, index=True),
                            LocalDeliveryProof._identity(base))
                result = self.check("staged-v1", {"index": staged, "base": base})
                self.assertEqual(result, dict(zip(("staged", "base"), expected)))
                with patch.dict(os.environ, self.env, clear=True), patch.object(
                        LocalDeliveryProof, "_identity", side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, _capture_identities(staged, base))

        for bad in ("100644 ab 2\tx\0", "missing tab", "100644 ab 0 extra\tx"):
            result = self.raw("staged-v1", {"index": bad, "base": tree})
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
            with patch.dict(os.environ, self.env, clear=True), self.assertRaises(ValueError):
                _capture_identities(bad, tree)

    def test_pending_publication_encoder_preserves_atomic_write_and_exact_bytes(self):
        path = self.base / "pending-publication.json"
        payload = {"z": [{"b": "한글🐈", "a": []}], "A": {}, "가": None,
                   "escape": '\x00\b\t\n\f\r\x1f\x7f"\\/', "count": 2**64 - 1}
        expected = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        result = self.raw("pending-publication-encode", payload)
        self.assertEqual((0, expected, b""), (result.returncode, result.stdout, result.stderr))

        path.write_bytes(b"previous\n")
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_execution_capsule_state._encoded_json", side_effect=AssertionError("Python fallback")):
            atomic_write_json(path, payload, write_payload=NativeProbe.encode_publication_receipt)
        self.assertEqual(expected, path.read_bytes())
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        with patch.dict(os.environ, self.env, clear=True), path.open("rb") as read_only:
            self.assertFalse(NativeProbe.encode_publication_receipt(payload, read_only))
        self.assertEqual(expected, path.read_bytes())

        def partial(_, stream):
            self.assertEqual(expected, path.read_bytes())
            stream.write(b"old oversized output" * 100)
            return False

        atomic_write_json(path, payload, write_payload=partial)
        self.assertEqual(expected, path.read_bytes())

        def failed(_, stream):
            stream.write(b"partial")
            raise OSError("write failed")

        with self.assertRaisesRegex(OSError, "write failed"):
            atomic_write_json(path, payload, write_payload=failed)
        self.assertEqual(expected, path.read_bytes())
        self.assertFalse(list(path.parent.glob(path.name + ".*.tmp")))
        collision = path.with_name(path.name + ".existing.tmp")
        collision.write_bytes(b"another writer's temporary file")
        with patch("agent_execution_capsule_state.uuid.uuid4") as uuid:
            uuid.return_value.hex = "existing"
            with self.assertRaises(FileExistsError):
                atomic_write_json(path, payload, write_payload=partial)
        self.assertEqual(b"another writer's temporary file", collision.read_bytes())
        self.assertEqual(expected, path.read_bytes())

        unusual = {**payload, "decimal": 1e-5, "large": 2**100}
        result = self.raw("pending-publication-encode", unusual)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        with patch.dict(os.environ, self.env, clear=True):
            atomic_write_json(path, unusual, write_payload=NativeProbe.encode_publication_receipt)
        self.assertEqual((json.dumps(unusual, sort_keys=True, indent=2) + "\n").encode(), path.read_bytes())

    def test_native_receipt_replacement_is_bound_and_atomic(self):
        run, nonce = "a" * 32, "b" * 32
        directory = self.project / ".moru" / "runs" / run
        directory.mkdir(parents=True)
        evidence = directory / "preflight.json"
        evidence.write_bytes(b"{}\n")
        target = directory / "pending-publication.json"
        record = {
            "schema_version": 1, "run_id": run, "base_head": "c" * 40,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "items": [{"checkpoint": "publication.commit", "state": "pending", "observation": "한글"}],
        }
        request = {"evidence": str(evidence), "temporary": nonce, "record": record}
        target.write_bytes(b"old\n")
        temporary = target.with_name(f"{target.name}.{nonce}.tmp")
        temporary.write_bytes(b"another writer")
        self.assertEqual({"error": "FileExistsError"}, self.check("pending-publication-replace", request))
        self.assertEqual(b"another writer", temporary.read_bytes())
        self.assertEqual(b"old\n", target.read_bytes())
        temporary.unlink()
        for changes in ({"run_id": "d" * 32}, {"evidence_sha256": "0" * 64},
                        {"opaque": "project_local_never_sync"},
                        {f".moru/runs/{run}/continuation.json?query": "rejected"}):
            refused = self.raw("pending-publication-replace", {**request, "record": {**record, **changes}})
            self.assertEqual((125, b"", b""), (refused.returncode, refused.stdout, refused.stderr))
            self.assertEqual(b"old\n", target.read_bytes())
            self.assertFalse(temporary.exists())
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_pending_publication.atomic_write_json", side_effect=AssertionError("Python fallback")):
            _store(evidence, record)
        self.assertEqual((json.dumps(record, sort_keys=True, indent=2) + "\n").encode(), target.read_bytes())
        self.assertEqual(0o600, target.stat().st_mode & 0o777)
        self.assertFalse(list(directory.glob("*.tmp")))
        alias = directory.with_name("e" * 32)
        alias.symlink_to(directory, target_is_directory=True)
        aliased = self.raw("pending-publication-replace", {
            **request, "evidence": str(alias / evidence.name), "record": {**record, "run_id": alias.name},
        })
        self.assertEqual((125, b"", b""), (aliased.returncode, aliased.stdout, aliased.stderr))
        with patch.dict(os.environ, self.env, clear=True), self.assertRaises(OSError):
            _store(alias / evidence.name, {**record, "run_id": alias.name})
        self.assertEqual((json.dumps(record, sort_keys=True, indent=2) + "\n").encode(), target.read_bytes())
        old_target = directory / "external-object"
        old_target.write_bytes(b"linked content")
        target.unlink()
        target.symlink_to(old_target)
        self.assertEqual({"error": None}, self.check("pending-publication-replace", request))
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"linked content", old_target.read_bytes())
        target.unlink()
        target.mkdir()
        with self.assertRaises(OSError) as failure:
            atomic_write_json(target, record)
        self.assertEqual({"error": type(failure.exception).__name__},
                         self.check("pending-publication-replace", request))
        self.assertFalse(list(directory.glob("*.tmp")))
        self.assertTrue(target.is_dir())

    def test_receipt_write_transport_does_not_retry_unknown_outcomes(self):
        evidence = self.project / "preflight.json"
        record = {"data": True}
        with patch.dict(os.environ, self.env, clear=True), patch(
                "agent_pending_publication.atomic_write_json") as legacy, patch(
                "support.native_probe_transport.subprocess.run") as native:
            for status, stdout in ((1, b""), (0, b""), (-9, b"")):
                native.return_value = subprocess.CompletedProcess([], status, stdout, b"")
                with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                    _store(evidence, record)
            native.side_effect = subprocess.TimeoutExpired([], 10)
            with self.assertRaisesRegex(OSError, "outcome could not be determined"):
                _store(evidence, record)
            legacy.assert_not_called()
            native.side_effect = None
            native.return_value = subprocess.CompletedProcess([], 125, b"", b"")
            _store(evidence, record)
            legacy.assert_called_once_with(evidence.with_name("pending-publication.json"), record,
                                           write_payload=NativeProbe.encode_publication_receipt)

    def test_pending_publication_transitions_preserve_receipt_order_and_metadata(self):
        fields = {"run_id": "test-run", "evidence_sha256": "1" * 64, "base_head": "2" * 40,
                  "source_branch": "reviewed"}
        checkpoints = ["publication.integrate/main", "publication.commit", "publication.integrate/main",
                       "publication.push"]
        local = {"targets": {"main": "2" * 40}, "extension": [None, True, 2**63]}
        baseline = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}
        observed_at = "2026-05-28T00:00:00+00:00"
        oid = "3" * 40
        for proof in (None, local):
            with patch.dict(os.environ, baseline, clear=True):
                record = _new_record(fields, checkpoints, proof)
            result = self.check("pending-publication-prepare", {
                **fields, "checkpoints": checkpoints, "local_delivery": proof,
            })
            self.assertEqual({"record": record}, result)
            with patch.dict(os.environ, self.env, clear=True):
                self.assertEqual(record, _new_record(fields, checkpoints, proof))
            self.assertEqual(list(dict.fromkeys(checkpoints)), [item["checkpoint"] for item in record["items"]])

            record["extension"] = [None, {"漢字": "🎉"}]
            commit = record["items"][1]
            record["items"].insert(0, {**commit, "state": "observed", "observation": "prior"})
            record["items"].append({**commit, "historical": True})
            for checkpoint, observation in (("publication.commit", f"committed as {oid}"),
                                            ("publication.push", f"pushed {oid}"),
                                            ("publication.integrate/main", f"integrated {oid} ")):
                with self.subTest(version=record["schema_version"], checkpoint=checkpoint):
                    reference = json.loads(json.dumps(record))
                    item = next(i for i in reference["items"]
                                if i["checkpoint"] == checkpoint and i["state"] == "pending")
                    with patch.dict(os.environ, baseline, clear=True):
                        expected = _observed_record(reference, item, observation, observed_at)
                    result = self.check("pending-publication-observe", {
                        "record": record, "checkpoint": checkpoint, "observation": observation,
                        "observed_at": observed_at,
                    })
                    self.assertEqual({"record": expected}, result)
                    original = json.loads(json.dumps(record))
                    item = next(i for i in record["items"]
                                if i["checkpoint"] == checkpoint and i["state"] == "pending")
                    with patch.dict(os.environ, self.env, clear=True):
                        self.assertEqual(expected, _observed_record(record, item, observation, observed_at))
                    self.assertEqual(original, record)
                    if proof is None:
                        self.assertNotIn("local_delivery", expected)
                    else:
                        cache = oid if checkpoint == "publication.commit" else None
                        self.assertEqual(cache, expected["local_delivery"].get("reviewed_commit"))

    def test_pending_publication_launcher_uses_native_status_without_losing_bound_debt(self):
        folder = self.base / "bound"
        folder.mkdir()
        with patch.dict(os.environ, self.env, clear=True):
            run = Run(str(folder), packet=True, writable=True, command="commit",
                      effect="git_write", authority="envelope")
        status = [str(self.entry), "pending-publication", "status",
                  "--evidence", str(run.evidence), "--project", str(run.project)]

        def invoke(backend="auto", empty=False, args=status):
            env = {**self.env, "MORU_LAUNCHER_BACKEND": backend}
            if empty:
                env["PATH"] = str(self.empty)
            done = subprocess.run(args, cwd=run.project, env=env, capture_output=True, timeout=15)
            return done.returncode, done.stdout, done.stderr

        self.assertEqual((0, b"no pending publication\n", b""), invoke(empty=True))
        items = [{"checkpoint": "publication.commit", "action": "Commit the reviewed files"}]
        with patch.dict(os.environ, self.env, clear=True):
            write_continuation_checkpoint(
                project=run.project, rules=run.project, run_id=run.run["run_id"], kind="initial",
                phase="acting", binding_path=run.evidence,
                work={"objective": "Finish the reviewed local commit", "remaining_work": items},
            )
        owed = invoke("python")
        self.assertEqual(0, owed[0])
        self.assertIn(b"(publication.commit)", owed[1])
        self.assertEqual(owed, invoke())
        self.assertEqual(127, invoke(empty=True)[0])

        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual("", record_pending(run.project, run.evidence, items))
        self.assertEqual(owed, invoke(empty=True))
        trailing_slash = [value + "/" if value == str(run.evidence) else value for value in status]
        self.assertEqual(owed, invoke(empty=True, args=trailing_slash))
        receipt = run.evidence.with_name("pending-publication.json")
        record = json.loads(receipt.read_text())
        record["items"][0]["state"] = "observed"
        receipt.write_text(json.dumps(record))
        self.assertEqual((0, b"no pending publication\n", b""), invoke(empty=True))
        self.assertEqual(invoke("python"), invoke(empty=True))
        run.evidence.with_name("continuation.json").write_text("{")
        self.assertEqual(invoke("python"), invoke())
        self.assertEqual(127, invoke(empty=True)[0])

    def test_pending_status_rules_out_unrecorded_debt_without_eligible_authority(self):
        actions = [{"checkpoint": "publication.push", "action": "Observe upstream"},
                   {"checkpoint": "publication.pull-request/main", "action": "Observe PR"}]
        for command, effect, authority, expected_debt in (
            ("commit", "git_write", "envelope", False),
            ("commit", "external_write", "envelope", True),
            ("refactor", "external_write", "envelope", False),
            ("commit", "external_write", "assumed", False),
        ):
            with self.subTest(command=command, effect=effect, authority=authority):
                folder = self.base / f"{command}-{effect}-{authority}"
                folder.mkdir()
                with patch.dict(os.environ, self.env, clear=True):
                    run = Run(str(folder), packet=True, writable=True, command=command,
                              effect=effect, authority=authority)
                    write_continuation_checkpoint(
                        project=run.project, rules=run.project, run_id=run.run["run_id"], kind="initial",
                        phase="acting", binding_path=run.evidence,
                        work={"objective": "Observe published work", "remaining_work": actions},
                    )
                args = [str(self.entry), "pending-publication", "status", "--project",
                        str(run.project), "--evidence", str(run.evidence)]
                path = run.evidence.with_name("continuation.json")
                before = run.evidence.read_bytes(), path.read_bytes()
                reference = subprocess.run(args, capture_output=True, timeout=15,
                                           env={**self.env, "MORU_LAUNCHER_BACKEND": "python"})
                self.assertEqual((0, b""), (reference.returncode, reference.stderr))
                offline = subprocess.run(args, capture_output=True, timeout=15,
                                         env={**self.env, "PATH": str(self.empty)})
                if not expected_debt:
                    self.assertEqual(b"no pending publication\n", reference.stdout)
                    self.assertEqual((0, reference.stdout, b""), (offline.returncode, offline.stdout, offline.stderr))
                else:
                    self.assertIn(b"publication.push, publication.pull-request/main", reference.stdout)
                    self.assertEqual(127, offline.returncode)
                self.assertEqual(before, (run.evidence.read_bytes(), path.read_bytes()))
                self.assertFalse(run.evidence.with_name("pending-publication.json").exists())
                if effect == "git_write":
                    run.evidence.write_bytes(b"{corrupt")
                    declined = subprocess.run(args, capture_output=True, timeout=15,
                                              env={**self.env, "PATH": str(self.empty)})
                    self.assertEqual(127, declined.returncode)
                    self.assertEqual(b"{corrupt", run.evidence.read_bytes())
                    self.assertEqual(before[1], path.read_bytes())

    def test_legacy_local_settlement_launcher_needs_git_but_no_python_or_registry(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        def commit(message):
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", message)
            return git("rev-parse", "HEAD")

        file = self.project / "tracked.txt"
        file.write_text("base\n")
        git("add", file.name)
        base = commit("base")
        run = self.project / ".moru" / "runs" / ("a" * 32)
        run.mkdir(parents=True)
        evidence = run / "preflight.json"
        evidence.write_bytes(b"{}\n")
        receipt = run / "pending-publication.json"
        checkpoint = "publication.commit"
        integration = "publication.integrate/main"
        receipt.write_text(json.dumps({
            "schema_version": 1, "run_id": run.name, "base_head": base, "source_branch": "main",
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "items": [{"checkpoint": item, "state": "pending"} for item in (checkpoint, integration)],
        }))
        before = receipt.read_bytes()
        (self.empty / "git").symlink_to(shutil.which("git"))

        def launcher(action=checkpoint, *, legacy=False):
            env = ({**self.env, "MORU_LAUNCHER_BACKEND": "python"} if legacy else
                   {**self.env, "PATH": str(self.empty)})
            args = [str(self.entry), "pending-publication", "settle", "--checkpoint", action,
                    "--evidence", str(evidence), "--project", str(self.project)]
            result = subprocess.run(args, env=env, capture_output=True, timeout=15)
            return result.returncode, result.stdout, result.stderr

        def refused(reason, action=checkpoint):
            expected = (2, f"FAIL publication settle: {reason}\n".encode(), b"")
            self.assertEqual(expected, launcher(action, legacy=True))
            self.assertEqual(expected, launcher(action))
            self.assertEqual(before, receipt.read_bytes())

        refused("local integration requires a bound staged-content proof", integration)
        refused("HEAD has not advanced from the finished commit base")
        file.write_text("reviewed\n")
        git("add", file.name)
        head = commit("reviewed")
        git("checkout", "--detach")
        refused("source branch differs from the finished publication")
        git("checkout", "main")
        file.write_text("dirty\n")
        refused("tracked changes remain uncommitted")
        file.write_text("reviewed\n")
        (self.project / "untracked.txt").write_text("ignored by legacy proof")
        self.assertEqual((0, b"publication observation recorded\n", b""), launcher())
        record = json.loads(receipt.read_bytes())
        self.assertNotIn("local_delivery", record)
        self.assertEqual(f"HEAD {head} descends from {base}", record["items"][0]["observation"])
        self.assertEqual("pending", record["items"][1]["state"])
        self.assertFalse((self.project / ".moru" / "run-registry.json").exists())

    def test_pending_publication_partition_preserves_admitted_effect_and_original_items(self):
        opaque = object()
        commit = {"checkpoint": "publication.commit", "action": opaque}
        integrate = {"checkpoint": "publication.integrate/main"}
        push = {"checkpoint": "publication.push"}
        pr = {"checkpoint": "publication.pull-request/develop"}
        invalid = {"checkpoint": "publication.pull-request/-invalid"}
        remaining = [pr, commit, invalid, None, integrate, push, commit, {"checkpoint": "publication.integrate"}]
        fallback = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}
        original_request = NativeProbe.request
        for command, effect, local, authority, schema, failures, positions in (
            ("commit", "git_write", False, "envelope", True, [], [1, 6]),
            ("commit", "external_write", False, "envelope", True, [], [0, 1, 5, 6]),
            ("commit", "external_write", True, "envelope", True, [], [0, 1, 4, 5, 6]),
            ("task", "git_write", True, "envelope", True, [], [1, 4, 6]),
            ("task", "external_write", True, "envelope", True, [], [1, 4, 6]),
            ("task", "local_write", True, "envelope", True, [], []),
            ("task", "external_write", True, "assumed", True, [], []),
            ("task", "external_write", True, "envelope", False, [], []),
            ("task", "external_write", True, "envelope", True, ["invalid"], []),
            ("review", "external_write", True, "envelope", True, [], []),
        ):
            with self.subTest(command=command, effect=effect, local=local, authority=authority, schema=schema,
                              failures=failures):
                envelope = {"effective_effect": effect, "authority": authority,
                            "schema_valid": schema, "failures": failures}
                route = {"command": command, "request_classification": {"intent_envelope": envelope}}
                if local:
                    route["local_delivery_contract"] = LocalDeliveryProof.CONTRACT
                with patch.dict(os.environ, fallback, clear=True):
                    expected = split_remaining({"route": route}, remaining)
                seen = []

                def request(*args):
                    result = original_request(*args)
                    seen.append(result)
                    return result

                with patch.dict(os.environ, self.env, clear=True), patch(
                        "agent_pending_publication.NativeProbe.request", side_effect=request):
                    actual = split_remaining({"route": route}, remaining)
                self.assertEqual(expected, actual)
                self.assertEqual([remaining[index] for index in positions], actual[1])
                self.assertTrue(all(item is remaining[index] for item, index in zip(actual[1], positions)))
                mask = [index in positions for index in range(len(remaining))]
                self.assertEqual([] if command == "review" else [{"deferred": mask}], seen)

    def test_pending_publication_status_preserves_debt_and_order_from_bound_receipts(self):
        run = self.base / "status-run"
        run.mkdir()
        evidence = run / "preflight.json"
        receipt = run / "pending-publication.json"
        evidence.write_bytes(b"fixture")
        names = ["publication.commit", "publication.push", "publication.integrate/main", "publication.push",
                 "publication.pull-request/main"]
        declared = [{"checkpoint": name} for name in names] + [{"checkpoint": "ignored"}, None]
        fallback = {**self.env, "MORU_LAUNCHER_BACKEND": "python"}

        def compare(wanted):
            checkpoints = declared if wanted else []
            with patch.dict(os.environ, fallback, clear=True), patch(
                    "agent_pending_publication.declared_deferrable", return_value=checkpoints):
                expected = outstanding(self.project, evidence, checkpoints), pending_reason(self.project, evidence)
            self.assertEqual({"owed": expected[0], "reason": expected[1]},
                             self.check("pending-publication-status", {
                                 "evidence": str(evidence), "declared": names if wanted else [],
                             }))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_pending_publication._outstanding_python", side_effect=AssertionError("Python fallback")
            ), patch("agent_pending_publication.declared_deferrable", return_value=checkpoints):
                self.assertEqual(expected, (outstanding(self.project, evidence, checkpoints),
                                            pending_reason(self.project, evidence)))
            return expected[0]

        self.assertEqual([], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))
        receipt.write_bytes(b"\xff")
        self.assertEqual(["receipt (unreadable)"], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))
        receipt.write_bytes(b"")
        result = self.raw("pending-publication-status", {"evidence": str(evidence), "declared": []})
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(["receipt (unreadable)"], outstanding(self.project, evidence))
        record = {"schema_version": 2, "run_id": run.name, "base_head": "base",
                  "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                  "items": [{"checkpoint": "publication.integrate/main", "state": "pending"},
                            {"checkpoint": "publication.commit", "state": "observed"},
                            {"checkpoint": "publication.integrate/main", "state": "pending"}]}
        receipt.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(["publication.integrate/main", "publication.integrate/main",
                          "publication.push", "publication.pull-request/main"], compare(True))
        evidence.write_bytes(b"changed")
        self.assertEqual(["receipt (foreign or malformed)"], compare(False))
        self.assertEqual(list(dict.fromkeys(names)), compare(True))

    def test_pending_publication_reads_verify_raw_evidence_and_keep_reference_fallback(self):
        run = self.base / "run-fixture"
        run.mkdir()
        evidence = run / "preflight.json"
        receipt = run / "pending-publication.json"
        payload = {"evidence": str(evidence)}
        raw_evidence = b'{\r\n"source": "fixture"\r\n}\r\n'
        evidence.write_bytes(raw_evidence)
        record = {"schema_version": 2, "run_id": run.name,
                  "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(), "base_head": "base",
                  "items": [{"checkpoint": "publication.commit", "state": "observed"},
                            {"checkpoint": "publication.integrate/" + "x" * 200, "state": "pending"}],
                  "opaque": {"label": "한글🐈", "count": 2**64 - 1, "optional": None}}

        def compare_native():
            expected = _load_python(evidence)
            self.assertEqual({"record": expected[0], "problem": expected[1]},
                             self.check("pending-publication-read", payload))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_pending_publication._load_python", side_effect=AssertionError("Python fallback")):
                self.assertEqual(expected, _load(evidence))

        compare_native()
        for changes in ({}, {"schema_version": 1}, {"schema_version": True}, {"run_id": "foreign"},
                        {"items": [{"checkpoint": "publication.integrate/" + "x" * 201, "state": "pending"}]},
                        {"items": [{"checkpoint": "publication.push", "state": "unknown"}]}):
            with self.subTest(changes=changes):
                receipt.write_text(json.dumps({**record, **changes}), encoding="utf-8")
                compare_native()
        receipt.write_bytes(b"[]")
        compare_native()
        duplicate = json.dumps(record).replace('"schema_version": 2', '"schema_version": 3, "schema_version": 2')
        receipt.write_text(duplicate, encoding="utf-8")
        compare_native()
        receipt.write_text(json.dumps(record), encoding="utf-8")
        evidence.write_bytes(evidence.read_bytes().replace(b"\r\n", b"\n"))
        compare_native()
        evidence.unlink()
        compare_native()
        receipt.write_bytes(b"\xff")
        compare_native()
        evidence.write_bytes(raw_evidence)
        for body in (b"{", json.dumps({**record, "schema_version": 1.0}).encode(),
                     json.dumps({**record, "opaque": 2**100}).encode(),
                     json.dumps({**record, "opaque": "\ud800"}).encode()):
            receipt.write_bytes(body)
            result = self.raw("pending-publication-read", payload)
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
            with patch.dict(os.environ, self.env, clear=True):
                self.assertEqual(_load_python(evidence), _load(evidence))
        receipt.unlink()
        os.mkfifo(receipt)
        result = self.raw("pending-publication-read", payload)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

    def test_local_delivery_prepares_exact_receipt_from_linked_worktree(self):
        repo = self.project

        def git(project, *args):
            return subprocess.run(["git", "-C", str(project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        git(repo, "config", "user.email", "fixture@example.invalid")
        git(repo, "config", "user.name", "Fixture")
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "base")
        base = git(repo, "rev-parse", "HEAD")
        work = self.base / "linked"
        git(repo, "worktree", "add", "-qb", "delivery", str(work))
        git(work, "commit", "--allow-empty", "-qm", "new HEAD")
        head = git(work, "rev-parse", "HEAD")
        alias = self.base / "linked-alias"
        alias.symlink_to(work, target_is_directory=True)
        file = work / "tracked.txt"
        items = [{"checkpoint": "publication.commit"}, {"checkpoint": "publication.integrate/main"}]

        def unexpected_git(*args):
            self.fail("native preparation fell back to the Python Git reader")

        def compare(checkpoints=items, expected_head=head, reason=""):
            with patch.dict(os.environ, self.env, clear=True):
                if reason:
                    with self.assertRaisesRegex(ValueError, reason):
                        LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints, _git)
                    with self.assertRaisesRegex(ValueError, reason):
                        LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints,
                                                   unexpected_git, native=True)
                else:
                    reference = LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints, _git)
                    actual = LocalDeliveryProof.capture(alias, expected_head, "delivery", checkpoints,
                                                        unexpected_git, native=True)
                    self.assertEqual(reference, actual)
                    self.assertEqual(str(work.resolve()), actual["project"])
                    self.assertEqual(str((repo / ".git").resolve()), actual["common"])

        (work / "untracked.txt").write_text("ignored by Git diff\n", encoding="utf-8")
        compare(checkpoints=items[1:])
        git(work, "branch", "other-target", head)
        checkpoint = "publication.integrate/other-target"
        with patch.dict(os.environ, self.env, clear=True):
            proof = LocalDeliveryProof.capture(alias, head, "delivery", [{"checkpoint": checkpoint}], _git)
            record = {"base_head": head, "source_branch": "delivery", "local_delivery": proof}
            self.assertEqual((f"target other-target contains reviewed commit {head}", ""),
                             LocalDeliveryProof.observe(alias, record, checkpoint, unexpected_git, native=True))
            self.assertEqual(("", "local delivery belongs to a different repository or checkout"),
                             LocalDeliveryProof.observe(repo, record, checkpoint, unexpected_git, native=True))
        compare(reason="stage the reviewed changes")
        file.write_text("unstaged\n", encoding="utf-8")
        compare(reason="tracked worktree content")
        git(work, "add", "tracked.txt")
        compare()
        compare(checkpoints=items[1:], reason="declare a local commit")
        compare(expected_head=base, reason="HEAD changed")
        compare(checkpoints=items[:1] + [{"checkpoint": "publication.integrate/delivery"}],
                reason="valid different target branch")
        git(repo, "tag", "tag-only")
        compare(checkpoints=items[:1] + [{"checkpoint": "publication.integrate/tag-only"}],
                reason="target must already exist")
        old_blob = git(work, "rev-parse", "HEAD:tracked.txt")
        subprocess.run(["git", "-C", str(work), "update-index", "--index-info"],
                       input=f"0 {'0' * len(old_blob)}\ttracked.txt\n100644 {old_blob} 2\ttracked.txt\n",
                       text=True, check=True, capture_output=True, env=self.env, timeout=5)
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaises(ValueError) as reference:
                LocalDeliveryProof.capture(alias, head, "delivery", items, _git)
            with self.assertRaises(ValueError) as actual:
                LocalDeliveryProof.capture(alias, head, "delivery", items, _git, native=True)
            self.assertEqual(str(reference.exception), str(actual.exception))

    def test_local_delivery_search_keeps_cache_order_and_scan_limit(self):
        project = self.project

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True,
                                  capture_output=True, text=True, env=self.env, timeout=5).stdout.strip()

        def commit(label, content=None):
            if content is not None:
                (project / "receipt.txt").write_text(content, encoding="utf-8")
                git("add", "receipt.txt")
            git("commit", "--allow-empty", "-qm", label)
            return git("rev-parse", "HEAD")

        def digest(oid):
            return LocalDeliveryProof._identity(git("ls-tree", "-r", "-z", oid))

        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        base = commit("base")
        first = commit("first match", "proof")
        different = commit("different", "other")
        second = commit("second match", "proof")
        for _ in range(60):
            commit("same tree")
        boundary = commit("64th commit", "inside limit")
        head = commit("65th commit", "outside limit")
        git("branch", "source", head)
        git("branch", "integration", base)
        payload = {"project": str(project), "recorded_project": str(project),
                   "recorded_common": str(project / ".git"), "base": base, "source": "source", "targets": ["integration"],
                   "checkpoint": "publication.commit", "commit_declared": True}

        def observe(**overrides):
            result = self.raw("staged-v1-observe", {**payload, **overrides}, PATH=os.defpath)
            self.assertEqual((0, b""), (result.returncode, result.stderr))
            return json.loads(result.stdout)["result"]

        for target, cached, expected in (
            (first, "", first), (first, second, second), (first, different, first),
            (boundary, "", boundary), (head, "", ""),
        ):
            with self.subTest(target=target, cached=cached):
                result = observe(cached=cached, expected=digest(target))
                if expected:
                    self.assertEqual({"observation": f"reviewed staged content committed as {expected}",
                                      "reason": ""}, result)
                else:
                    self.assertEqual({"observation": "",
                                      "reason": "the reviewed staged content has not been observed in a commit"}, result)

        request = {**payload, "cached": "", "expected": digest(first)}
        result = self.raw("staged-v1-observe", request)
        self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))

        record = {"schema_version": 2, "base_head": base, "source_branch": "main",
                  "local_delivery": {"project": str(project), "common": str(project / ".git"),
                                     "commit_declared": True, "staged_sha256": digest(first), "targets": {}}}
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(LocalDeliveryProof, "_common", side_effect=AssertionError("Python fallback")):
                self.assertEqual((f"reviewed staged content committed as {first}", ""),
                                 _observe(project, record, {"checkpoint": "publication.commit"}))
            with patch("agent_pending_publication._git", wraps=_git) as reader:
                self.assertEqual((f"reviewed staged content committed as {first}", ""),
                                 _observe(project, record, {"checkpoint": "publication.commit"}))
                self.assertIn(("ls-tree", "-r", "-z", first), [call.args[1:] for call in reader.call_args_list])

        args = {"checkpoint": "publication.integrate/integration", "cached": "", "expected": digest(first)}
        self.assertEqual("target branch does not contain the reviewed commit", observe(**args)["reason"])
        self.assertEqual("local integration target was not prepared", observe(**{**args, "targets": []})["reason"])
        git("branch", "-f", "integration", head)
        integrated = f"target integration contains reviewed commit {first}"
        self.assertEqual(integrated, observe(**args)["observation"])
        git("branch", "-f", "source", base)
        self.assertEqual("local delivery proof cannot be verified", observe(**{**args, "base": first})["reason"])
        git("branch", "-D", "source")
        self.assertEqual(integrated, observe(**args)["observation"])
        self.assertEqual(f"target integration contains reviewed commit {base}",
                         observe(**{**args, "commit_declared": False})["observation"])
        record["source_branch"] = "source"
        record["local_delivery"]["targets"] = {"integration": base}
        with patch.dict(os.environ, self.env, clear=True), patch.object(
                LocalDeliveryProof, "_common", side_effect=AssertionError("Python fallback")):
            self.assertEqual((integrated, ""), _observe(project, record, {"checkpoint": args["checkpoint"]}))
            record["local_delivery"]["common"] = str(project / "foreign.git")
            self.assertEqual(("", "local delivery belongs to a different repository or checkout"),
                             _observe(project, record, {"checkpoint": args["checkpoint"]}))

    def test_native_upstream_config_preserves_remote_query_boundary(self):
        project = self.project
        payload = {"project": str(project)}
        head = "1" * 40
        reference = "refs/heads/main"
        env = {**self.env, "GIT_ALLOW_PROTOCOL": ""}

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True,
                                  text=True, env=env, timeout=5)

        def config():
            response = self.raw("publication-upstream-config", payload, PATH=os.environ["PATH"])
            self.assertEqual((0, b""), (response.returncode, response.stderr), response)
            return json.loads(response.stdout)["result"]

        def read_git(path, *args):
            if args[0] == "ls-remote":
                return f"{head}\t{reference}" if remote_succeeds else None
            return _git(path, *args)

        def remote_calls(expected, calls):
            with patch.dict(os.environ, env, clear=True), patch(
                    "agent_pending_publication._git", side_effect=read_git) as reader, patch(
                    "agent_pending_publication._LOCAL_DELIVERY_GIT", reader):
                self.assertEqual(expected, _remote_head(project, head))
                self.assertEqual(calls, [call.args[1:] for call in reader.call_args_list])

        remote_succeeds = True
        absent = ("", "the branch has no configured upstream to check")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])
        git("config", "--add", "branch.main.remote", "first")
        git("config", "--add", "branch.main.remote", " final ")
        git("config", "--add", "branch.main.merge", "refs/tags/no")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])
        git("config", "--add", "branch.main.merge", f" {reference}\n")
        self.assertEqual({"remote": "final", "merge": reference}, config())
        with patch.dict(os.environ, {**env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = observe_upstream(f"{head}\t{reference}", "final", reference, head)
            failed = observe_upstream(None, "final", reference, head)
        query = ("ls-remote", "--exit-code", "final", reference)
        remote_calls(expected, [query])
        remote_succeeds = False
        remote_calls(failed, [query])
        git("config", "--replace-all", "branch.main.remote", "--upload-pack=ignored")
        declined = self.raw("publication-upstream-config", payload, PATH=os.environ["PATH"])
        self.assertEqual((125, b"", b""), (declined.returncode, declined.stdout, declined.stderr))
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "base")
        git("checkout", "--detach")
        self.assertEqual({"remote": "", "merge": ""}, config())
        remote_calls(absent, [])

    def test_publication_evidence_matches_existing_provider_and_upstream_checks(self):
        path = self.base / "provider-proof.json"
        head, branch, target = "1" * 40, "feature", "main"
        record = {"exists": True, "source_branch": branch, "source_commit": head, "target_branch": target,
                  "state": "OPEN"}
        payload = {"path": str(path), "branch": branch, "head": head, "target": target}

        def compare():
            expected = _observe_pull_request_python(path, branch, head, target)
            self.assertEqual({"observation": expected[0], "reason": expected[1]},
                             self.check("publication-pr-proof", payload))
            with patch.dict(os.environ, self.env, clear=True), patch(
                    "agent_publication_status._observe_pull_request_python", side_effect=AssertionError("Python fallback")):
                self.assertEqual(expected, observe_pull_request(self.project, head, target, lambda *_: branch, path))

        for change in ({}, {"state": "MERGED"}, {"exists": 1}, {"target_branch": "develop"},
                       {"source_commit": head[:7]}, {"source_branch": "other"}, {"state": "CLOSED"},
                       {"state": "open"}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**record, **change}), encoding="utf-8")
                compare()
        raw = json.dumps(record).encode()
        path.write_bytes(raw.ljust(65_536, b" "))
        compare()
        path.write_bytes(raw.ljust(65_537, b" "))
        compare()
        path.write_bytes(raw + b"{}")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(("", "the provider observation could not be read as JSON"),
                             observe_pull_request(self.project, head, target, lambda *_: branch, path))

        reference = "refs/heads/main"
        wrong = "2" * 40
        for output in (f"{head}\t{reference}", f"{wrong}\t{reference}\n{head}\trefs/heads/other", "\u2003", None):
            with self.subTest(output=output):
                request = {"listed": output or "", "remote": "origin", "merge": reference, "head": head}
                with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
                    expected = observe_upstream(output, "origin", reference, head)
                self.assertEqual({"observation": expected[0], "reason": expected[1]},
                                 self.check("publication-upstream-proof", request))
                with patch.dict(os.environ, self.env, clear=True):
                    self.assertEqual(expected, observe_upstream(output, "origin", reference, head))

    def test_legacy_publication_head_matches_python_without_remote_checks(self):
        project = self.project

        def git(*args):
            return subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True,
                                  text=True, env=self.env, timeout=5).stdout.strip()

        git("config", "user.email", "fixture@example.invalid")
        git("config", "user.name", "Fixture")
        file = project / "tracked.txt"
        file.write_text("first", encoding="utf-8")
        git("add", "tracked.txt")
        git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        record = {"schema_version": 1, "source_branch": "main", "base_head": base, "items": []}

        def compare(checkpoint, value=record):
            with patch.dict(os.environ, self.env, clear=True):
                expected = _legacy_local_head_python(project, value, checkpoint)
                with patch("agent_pending_publication._legacy_local_head_python",
                           side_effect=AssertionError("Python fallback")):
                    self.assertEqual(expected, _legacy_local_head(project, value, checkpoint))
            return expected

        self.assertEqual((base, ""), compare("publication.push"))
        self.assertEqual(("", "HEAD has not advanced from the finished commit base"), compare("publication.commit"))
        git("commit", "--allow-empty", "-qm", "descendant with the same tree")
        head = git("rev-parse", "HEAD")
        self.assertEqual((head, ""), compare("publication.commit"))
        self.assertEqual(("", "HEAD is not the reviewed finish commit and no declared commit covers it"),
                         compare("publication.push"))
        self.assertEqual((head, ""), compare("publication.push", {
            **record, "items": [{"checkpoint": "publication.commit"}],
        }))
        file.write_text("dirty", encoding="utf-8")
        self.assertEqual(("", "tracked changes remain uncommitted"), compare("publication.commit"))
        git("add", "tracked.txt")
        self.assertEqual(("", "tracked changes remain uncommitted"), compare("publication.commit"))
        git("checkout", "--detach", "-q", head)
        self.assertEqual(("", "source branch differs from the finished publication"), compare("publication.commit"))

    def test_quality_warns_without_executing_commands_or_printing_command_content(self):
        marker = self.project / "never-created"
        records = [{"gate": "tests", "status": "SUCCESS", "fields": {"check": cmd, "result": "1 test passed"}}
                   for cmd in ("echo success", "printf 'done'", "true", ":", "exit 0",
                               f"echo ok && touch {marker}", "pytest -q", "echo $OBSERVED")]
        warnings = self.check("quality", {"records": records})["warnings"]
        self.assertEqual(5, len(warnings))
        self.assertTrue(all(row == {"gate": "tests", "rule": "fixed_output_check"} for row in warnings))
        self.assertFalse(marker.exists())
        records[0]["fields"] = {"check": "pytest", "result": "0 tests; exit 0"}
        records[1]["fields"]["result"] = "5 tests; 0 failures"
        rules = [v["rule"] for v in self.check("quality", {"records": records})["warnings"]]
        self.assertEqual(1, rules.count("zero_test_count"))

    def test_requirements_revision_duplicates_and_removal_are_checked(self):
        original = contract()
        self.assertEqual([], self.check("requirements", {"current": original, "previous": None})["failures"])
        changed = contract(owner="other")
        self.assertIn("requirements_revision_must_advance", self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["revision"] = 2
        self.assertEqual([], self.check("requirements", {"current": changed, "previous": original})["failures"])
        changed["items"][0]["id"] = "r2"
        self.assertIn("requirements_cannot_disappear", self.check("requirements", {"current": changed, "previous": original})["failures"])
        for value in ({"revision": True, "items": []}, {"revision": 1, "items": []},
                      {"revision": 1, "items": original["items"] * 2}, contract(artifacts=["../outside"]),
                      contract(artifacts=[".moru/hidden"]), contract(artifacts=["plan.md", "plan.md"])):
            with self.subTest(value=value):
                self.assertTrue(self.check("requirements", {"current": value})["failures"])

    def test_coverage_observes_gate_and_actual_artifact_and_rejects_symlinks(self):
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertTrue(self.check("coverage", value)["failures"])
        (self.project / "plan.md").write_text("Delivered plan\n")
        output = self.check("coverage", value)
        self.assertEqual([], output["failures"])
        self.assertEqual(64, len(output["observations"][0]["artifacts"]["plan.md"]))
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertTrue(self.check("coverage", value)["failures"])
        value["gates"] = [{"gate": "tests", "status": "SUCCESS"}]
        value["allowed_gates"] = ["other"]
        self.assertTrue(self.check("coverage", value)["failures"])
        value["allowed_gates"] = ["tests"]
        target = self.project / "actual.md"
        (self.project / "plan.md").rename(target)
        (self.project / "plan.md").symlink_to(target)
        self.assertTrue(self.check("coverage", value)["failures"])

    def test_progress_ignores_metadata_and_order_but_resets_for_acceptance_changes(self):
        work = {"remaining_work": [{"checkpoint": "tests", "action": "Check plan"},
            {"checkpoint": "review", "action": "Review plan"}], "blockers": ["second", "first"], "requirements": contract()}
        value = {"work": work, "gates": [{"gate": "tests", "status": "FAIL", "updated_at": "one"},
                                           {"gate": "review", "status": "SUCCESS"}]}
        first = self.check("progress", value)
        for index in range(2):
            value["previous"] = first
            value["updated_at"] = str(index)
            value["work"]["generation"] = index
            value["work"]["requirements"]["revision"] += 1
            value["work"]["remaining_work"].reverse()
            value["work"]["blockers"].reverse()
            value["gates"].reverse()
            value["gates"][0]["updated_at"] = str(index)
            first = self.check("progress", value)
        self.assertTrue(first["stalled"])
        self.assertEqual(2, first["repeats"])
        value["previous"] = first
        value["gates"][0]["status"] = "SUCCESS"
        final = self.check("progress", value)
        self.assertEqual(0, final["repeats"])
        self.assertFalse(final["stalled"])

    def test_long_gate_history_preserves_latest_failure(self):
        (self.project / "plan.md").write_text("Delivered\n")
        value = {"current": contract(), "project": str(self.project), "allowed_gates": ["tests"],
                 "gates": [{"gate": "tests", "status": "SUCCESS"}] * 1024}
        self.assertEqual([], self.check("coverage", value)["failures"])
        value["gates"].append({"gate": "tests", "status": "FAIL"})
        self.assertIn("observing gate", self.check("coverage", value)["failures"][0])
        value["gates"].append({"gate": "tests", "status": "SUCCESS"})
        self.assertEqual([], self.check("coverage", value)["failures"])

    def test_artifact_limits_return_specific_failures_at_exact_boundaries(self):
        for name in ("one.bin", "two.bin"):
            with (self.project / name).open("wb") as stream:
                stream.truncate(16 * 1024 * 1024)
        value = {"current": contract(artifacts=["one.bin", "two.bin"]), "project": str(self.project),
                 "allowed_gates": ["tests"], "gates": [{"gate": "tests", "status": "SUCCESS"}]}
        self.assertEqual([], self.check("coverage", value)["failures"])
        (self.project / "three.bin").write_bytes(b"x")
        value["current"]["items"][0]["artifacts"].append("three.bin")
        self.assertIn("32 MiB total limit", self.check("coverage", value)["failures"][0])
        with (self.project / "one.bin").open("ab") as stream:
            stream.write(b"x")
        self.assertTrue(any("16 MiB file limit" in failure for failure in self.check("coverage", value)["failures"]))
        (self.project / "one.bin").unlink()
        os.mkfifo(self.project / "one.bin")
        self.assertIn("unsafe", self.check("coverage", value)["failures"][0])

    def test_protocol_source_environment_and_python_rollback_boundaries(self):
        for op, payload in (("unknown", {}), ("quality", b"{broken"), ("quality", b" " * (1024 * 1024 + 1))):
            result = self.raw(op, payload, MORU_HOOK_SOFT_FAIL="1")
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
        self.assertEqual(125, self.raw("quality", {"records": []}, PYTHONVERBOSE="1").returncode)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual({"warnings": []}, completion_native("quality", {"records": []}))
            with patch.dict(os.environ, {"MORU_LAUNCHER_BACKEND": "python"}):
                self.assertIsNone(completion_native("quality", {"records": []}))


if __name__ == "__main__":
    unittest.main()
