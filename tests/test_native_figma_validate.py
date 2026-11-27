"""Offline Figma validator: exact reference output, refusals and no-Python proof."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import random
import shlex
import shutil
import struct
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from native_pretool_support import PROJECT, environment, prepare, result
from native_launcher_support import copied_build_root
from test_figma_validate import _valid_summary, _valid_v4_summary


class NativeFigmaValidate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-figma-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.entry, self.project = prepare(self.base)
        self.env = environment(self.base)
        self.empty_path = self.base / "no-executables"
        self.empty_path.mkdir()
        self.summary = self.base / "summary 한글.json"

    def call(self, args, backend="auto", **overrides):
        env = {**self.env, "MORU_LAUNCHER_BACKEND": backend, **overrides}
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([str(self.entry), "figma-validate", *args],
            cwd=self.project, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=20)

    def parity(self, payload):
        self.summary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = self.summary.read_bytes()
        args = [str(self.summary)]
        expected = self.call(args, backend="python")
        self.assertIn(expected.returncode, (0, 1), expected.stderr)
        self.assertEqual(result(expected), result(self.call(args)))
        self.assertEqual(result(expected), result(self.call(args, PATH=str(self.empty_path))))
        self.assertEqual(before, self.summary.read_bytes())
        self.assertTrue(expected.stdout.endswith(b"\n\n"))
        return expected

    def test_valid_and_nonobject_summaries(self):
        for payload in (_valid_summary(), _valid_v4_summary(), [], None, False, 123, "text"):
            with self.subTest(payload=payload):
                self.parity(payload)

    def test_extractor_dry_run_resolves_targets_through_real_probe(self):
        executable = self.entry.with_name("moru-hook-native")
        real = executable.with_name("original-native")
        executable.rename(real)
        log = self.base / "target-probes"
        executable.write_text(f'#!/bin/sh\n{shlex.quote(str(real))} "$@"\nstatus=$?\n'
                              f'printf "%s %s\\n" "$3" "$status" >> {shlex.quote(str(log))}\nexit "$status"\n')
        executable.chmod(0o700)
        script = PROJECT / "scripts/figma-handoff/figma-handoff.py"
        env = {**self.env, "PATH": str(self.empty_path)}
        cases = [
            (["--url", "https://www.figma.com/file/F/A?node_id=7-8&node-id=1-2&node-id=3-4",
              "--node-id", "9-9", "--file-key", "IGNORED"], ("F", "1:2"), 0),
            (["--url", "https://www.figma.com/design/D/F?node-id=I2%252D3%253B4%252D5"], ("D", "I2:3;4:5"), 0),
            (["--url", "https://www.figma.com/proto/P/S?node-id=&node_id=5-6"], ("P", "5:6"), 0),
            (["--url", "https://www.figma.com/design/EMPTY/S"], None, 0),
            (["--url", "https://[::1]/design/UNUSUAL/S?node-id=1-2"], ("UNUSUAL", "1:2"), 125),
        ]
        for args, target, probe_status in cases:
            command = [sys.executable, "-B", str(script), "--dry-run", *args]
            with self.subTest(args=args):
                log.write_text("")
                expected = subprocess.run(command, env={**env, "MORU_LAUNCHER_BACKEND": "python"}, cwd=self.project,
                                          capture_output=True, timeout=8)
                self.assertEqual("", log.read_text())
                observed = subprocess.run(command, env=env, cwd=self.project, capture_output=True, timeout=8)
                self.assertEqual(result(expected), result(observed))
                self.assertEqual([f"figma-target {probe_status}"], log.read_text().splitlines())
                if target is None:
                    self.assertNotEqual(0, observed.returncode)
                    self.assertIn(b"Missing Figma node id.", observed.stderr)
                else:
                    self.assertEqual(0, observed.returncode, observed.stderr)
                    plan = json.loads(observed.stdout)
                    self.assertEqual(target, (plan["fileKey"], plan["startNodeId"]))

    def test_public_live_smoke_alias_handles_offline_dispatch(self):
        clean = {k: v for k, v in self.env.items() if k not in ("FIGMA_TOKEN", "FIGMA_SMOKE_URL", "MOCK_TOKEN")}

        def invoke(args, backend="auto", **extra):
            return subprocess.run([str(self.entry), "figma-live-smoke", *args], cwd=self.project,
                                  env={**clean, "MORU_LAUNCHER_BACKEND": backend, **extra},
                                  stdin=subprocess.DEVNULL, capture_output=True, timeout=8)

        for args, variable, env in (([], "FIGMA_TOKEN", {}), (["--quick"], "FIGMA_TOKEN", {"FIGMA_TOKEN": ""}),
                                    (["--token-env", "MOCK_TOKEN"], "MOCK_TOKEN", {"FIGMA_TOKEN": "synthetic"})):
            with self.subTest(args=args):
                expected = invoke(args, "python", **env)
                self.assertEqual((0, f"SKIP: {variable} is not set — live smoke needs network + token.\n".encode(),
                                  b""), result(expected))
                self.assertEqual(result(expected), result(invoke(args, PATH=str(self.empty_path), **env)))
        for args, env in ((["--scale", "invalid"], {}), (["--unknown"], {}),
                          (["--token-env", "MOCK_TOKEN"], {"MOCK_TOKEN": "synthetic"})):
            with self.subTest(args=args):
                expected = invoke(args, "python", **env)
                self.assertEqual(2, expected.returncode)
                self.assertEqual(result(expected), result(invoke(args, **env)))
                self.assertEqual(127, invoke(args, PATH=str(self.empty_path), **env).returncode)

    def test_public_live_smoke_runs_synthetic_extractor_once_and_cleans_up(self):
        import live_smoke

        stub = self.empty_path / "python3"
        log = self.base / "extractor-args.jsonl"
        fixture = self.base / "bundle"
        (fixture / "summary").mkdir(parents=True)
        (fixture / "summary/design-summary.json").write_text(json.dumps(_valid_summary()))
        (fixture / "frames").mkdir()
        (fixture / "frames/1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 1, 1))
        (fixture / "assets").mkdir()
        (fixture / "assets/1.svg").touch()
        stub.write_text(f"#!{sys.executable}\n" + '''import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["TEST_LOG"]).open("a") as records:
    print(json.dumps(args), file=records)
if len(args) == 5 and Path(args[0]).name == "live_smoke.py" and args[1] == "--moru-inspect-bundle":
    os.execv(sys.executable, [sys.executable, *args])
if not args or Path(args[0]).name != "figma-handoff.py":
    sys.exit(94)
root = Path(args[args.index("--out") + 1])
assert root.is_dir()
print("  " + "표" * 610 + "  ")
print("  " + "오" * 810 + "  ", file=sys.stderr)
if os.environ["TEST_CHILD_STATUS"] == "fail":
    sys.exit(19)
shutil.copytree(os.environ["TEST_BUNDLE"], root / "smoke")
if os.environ["TEST_CHILD_STATUS"] == "compat":
    (root / "smoke/frames/link.png").symlink_to("1.png")
''')
        stub.chmod(0o700)
        url = "https://example.invalid/synthetic"
        for quick, status in ((False, "success"), (True, "success"), (False, "fail"), (True, "compat")):
            args = ["--token-env", "MOCK_TOKEN", "--scale", "1.25", "--url", url] + (["--quick"] if quick else [])
            env = {**self.env, "PATH": str(self.empty_path), "MOCK_TOKEN": "synthetic", "TEST_LOG": str(log),
                   "TEST_CHILD_STATUS": status, "TEST_BUNDLE": str(fixture)}
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(quick=quick, status=status), patch.dict(os.environ, {
                    **env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True), patch.object(
                    sys, "executable", str(stub)), patch.object(sys, "argv", ["live_smoke.py", *args]), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                expected_code = live_smoke.main()
            self.assertEqual(int(status == "fail"), expected_code, stderr.getvalue())
            log.write_text("")
            observed = subprocess.run([str(self.entry), "figma-live-smoke", *args], env=env, cwd=self.project,
                                      capture_output=True, stdin=subprocess.DEVNULL, timeout=8)
            self.assertEqual((expected_code, stdout.getvalue().encode(), stderr.getvalue().encode()), result(observed))
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(2 if status == "compat" else 1, len(records))
            child = records[0]
            out = Path(child[child.index("--out") + 1])
            self.assertEqual([str(live_smoke.TOOL), "--url", url, "--name", "smoke", "--out", str(out),
                              "--scale", "1.25", "--token-env", "MOCK_TOKEN"] +
                             ([] if quick else ["--export-assets"]), child)
            self.assertFalse(out.exists())
            if status == "compat":
                self.assertEqual([str(Path(live_smoke.__file__).resolve()), "--moru-inspect-bundle",
                                  str(out / "smoke"), "1", "1.25"], records[1])

    def test_imported_schema_reaches_native_for_bundle_and_offline_smoke(self):
        import figma_summary_validate as schema
        from figma_bundle_output import FigmaBundleOutput
        import live_smoke

        summary = _valid_summary()
        summary["designTokens"].update(colorStyles=[], textStyles=[], effectStyles=[])
        summary["meta"].update(fileKey="", startNodeId="")
        before = copy.deepcopy(summary)
        expected = ["meta.fileKey missing", "meta.startNodeId missing"]
        output = FigmaBundleOutput(self.base / "bundle")
        output.create_directories()
        args = SimpleNamespace(format="png", scale=1, max_flow_depth=1, no_images=True, include_image_fills=False)
        fake_token = "synthetic-only!"
        real_run = subprocess.run
        calls = []
        raw_summary = None

        def inspect_native(argv, **kwargs):
            self.assertIn(argv[-1], ("figma-summary-schema", "figma-smoke-file-result", "figma-smoke-result",
                                     "figma-smoke-verdict", "figma-smoke-frames"))
            self.assertNotIn("CUSTOM_SMOKE_TOKEN", kwargs["env"])
            self.assertNotIn(fake_token.encode(), kwargs["input"])
            calls.append(argv[-1])
            done = real_run(argv, **kwargs)
            if argv[-1] in ("figma-smoke-file-result", "figma-smoke-result"):
                request = json.loads(json.loads(kwargs["input"])["text"])
                keys = {"quick", "bundle_root", "scale"}
                if argv[-1] == "figma-smoke-result":
                    keys.add("summary")
                else:
                    self.assertLess(len(kwargs["input"]), 4096)
                self.assertEqual(keys, set(request))
                self.assertIs(type(request["quick"]), bool)
                self.assertEqual("smoke", Path(request["bundle_root"]).name)
                if raw_summary is not None:
                    self.assertEqual(125, done.returncode)
                    return done
                self.assertEqual((0, b""), (done.returncode, done.stderr))
                self.assertEqual({"stdout", "code", "after_cleanup"}, set(json.loads(done.stdout)["result"]))
            if argv[-1] == "figma-smoke-verdict":
                self.assertEqual((0, b""), (done.returncode, done.stderr))
                verdict = json.loads(done.stdout)["result"]
                self.assertEqual({"problems", "report", "coverage_failures"}, set(verdict))
            if argv[-1] == "figma-smoke-frames":
                request = json.loads(json.loads(kwargs["input"])["text"])
                self.assertIs(request["discover"], True)
                self.assertNotIn("frames", request)
                self.assertEqual((0, b""), (done.returncode, done.stderr))
            return done

        def fake_extractor(argv, **kwargs):
            self.assertEqual(str(live_smoke.TOOL), argv[1])
            root = Path(argv[argv.index("--out") + 1]) / "smoke"
            (root / "summary").mkdir(parents=True)
            (root / "summary/design-summary.json").write_text(raw_summary or json.dumps(smoke_summary))
            if with_assets:
                (root / "assets").mkdir()
                (root / "assets/.hidden.svg").write_text("<svg/>")
                (root / "assets/directory.svg").mkdir()
                (root / "assets/icon.png").touch()
                (root / "assets/ignored.SVG").touch()
            (root / "frames").mkdir()
            (root / "frames/one.png").write_bytes(bytes.fromhex(
                "89504e470d0a1a0a0000000d494844520000000100000001"))
            (root / "frames/.hidden.png").write_bytes(bytes.fromhex(
                "89504e470d0a1a0a0000000d494844520000000200000003"))
            (root / "frames/ignored.PNG").write_bytes(b"ignored")
            if not with_assets:
                for name in ("z.png", "a.png"):
                    (root / "frames" / name).write_bytes(b"bad")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with patch.dict(os.environ, {**self.env, "PATH": str(self.empty_path), "CUSTOM_SMOKE_TOKEN": fake_token},
                        clear=True), patch.object(schema, "_validate_summary_reference",
                        side_effect=AssertionError("unexpected Python schema fallback")), patch.object(
                        subprocess, "run", side_effect=inspect_native):
            self.assertEqual(expected, schema.validate_summary(summary))
            self.assertEqual(before, summary)
            self.assertEqual(expected, output.persist(summary, ["existing"], args))
            self.assertEqual({**before, "warnings": ["existing", *["schema: " + p for p in expected]]}, summary)
        self.assertEqual(["figma-summary-schema"] * 2, calls)

        def run_smoke(backend, quick=False):
            stream = io.StringIO()
            with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": backend, "PATH": str(self.empty_path),
                                         "CUSTOM_SMOKE_TOKEN": fake_token}, clear=True), patch.object(
                live_smoke, "subprocess", SimpleNamespace(run=fake_extractor)
            ), patch.object(subprocess, "run", side_effect=inspect_native), patch.object(
                sys, "argv", ["live_smoke.py", "--token-env", "CUSTOM_SMOKE_TOKEN",
                              "--url", "https://example.invalid/synthetic"] + (["--quick"] if quick else [])), redirect_stdout(stream):
                return live_smoke.main(), stream.getvalue()

        incomplete = _valid_summary()
        incomplete["screens"] = [{"id": "1", "name": "screen", "type": "FRAME"}]
        incomplete["assetCandidates"] = [
            {"id": str(i), "imageRefs": ["ref"], "assetPath": "a.png" if i < 199 else ""} for i in range(200)]
        large = {**_valid_summary(), "padding": "x" * (1024 * 1024 + 1)}
        for smoke_summary, status, with_assets in ((_valid_summary(), 0, True), (large, 0, True), (incomplete, 1, False)):
            with self.subTest(status=status):
                calls.clear()
                reference = run_smoke("python")
                self.assertEqual([], calls)
                observed = run_smoke("auto")
                self.assertEqual(reference, observed)
                self.assertEqual(status, observed[0])
                self.assertEqual(["figma-smoke-file-result"], calls)
                if status:
                    self.assertIn("frames=4 (for example: (2, 3)) assets: svg=0 png=0", observed[1])
                    self.assertLess(observed[1].index("invalid PNG: a.png"), observed[1].index("invalid PNG: z.png"))
                    self.assertLess(observed[1].index("layout coverage is empty for a non-empty handoff"),
                                    observed[1].index("image-fill recovery 199/200 (99%) < 100%"))
                else:
                    self.assertIn("frames=2 (for example: (2, 3)) assets: svg=2 png=1", observed[1])
        smoke_summary = incomplete
        expected_quick = run_smoke("python", quick=True)
        calls.clear()
        self.assertEqual(expected_quick, run_smoke("auto", quick=True))
        self.assertEqual(["figma-smoke-file-result"], calls)
        self.assertEqual(1, expected_quick[0])
        self.assertIn("layout coverage is empty for a non-empty handoff", expected_quick[1])
        self.assertNotIn("image-fill recovery", expected_quick[1])
        self.assertNotIn("no vector SVG assets exported", expected_quick[1])
        expected_failure = run_smoke("python")
        real_probe = live_smoke._probe
        def decline_file(operation, payload, source):
            return None if operation == "figma-smoke-file-result" else real_probe(operation, payload, source)

        with patch.object(live_smoke, "_probe", side_effect=decline_file):
            calls.clear()
            self.assertEqual(expected_failure, run_smoke("auto"))
            self.assertEqual(["figma-smoke-result"], calls)
        combined = {"stdout": "untrusted", "after_cleanup": "untrusted", "code": 0}
        for invalid in (None, {**combined, "code": True}, {**combined, "code": 2},
                        {**combined, "stdout": False}, {**combined, "after_cleanup": []}):
            def result_reply(operation, payload, source):
                if operation == "figma-smoke-file-result":
                    return None
                return invalid if operation == "figma-smoke-result" else real_probe(operation, payload, source)

            with self.subTest(result=invalid), patch.object(live_smoke, "_probe", side_effect=result_reply):
                calls.clear()
                self.assertEqual(expected_failure, run_smoke("auto"))
                self.assertEqual(["figma-smoke-verdict", "figma-smoke-frames"], calls)
        receipt = {"problems": [], "report": "untrusted", "coverage_failures": []}
        for malformed in (None, {**receipt, "report": None}, {**receipt, "coverage_failures": "invalid"},
                          {**receipt, "coverage_failures": [False]}, {**receipt, "problems": [17]}):
            def analysis_reply(operation, payload, source):
                if operation in ("figma-smoke-file-result", "figma-smoke-result"):
                    return None
                return malformed if operation == "figma-smoke-verdict" else real_probe(operation, payload, source)

            with self.subTest(reply=malformed), patch.object(live_smoke, "_probe", side_effect=analysis_reply):
                calls.clear()
                self.assertEqual(expected_failure, run_smoke("auto"))
                self.assertEqual(["figma-smoke-frames"], calls)
        discovered = {"frames": ["frames/a.png"], "failures": [], "svg_count": 0, "png_count": 0}
        for bad in ({**discovered, "svg_count": True}, {**discovered, "frames": ["../outside.png"]},
                    {**discovered, "frames": ["frames/z.png", "frames/a.png"]}):
            def malformed_discovery(operation, payload, source):
                if operation in ("figma-smoke-file-result", "figma-smoke-result"):
                    return None
                return bad if operation == "figma-smoke-frames" else real_probe(operation, payload, source)

            with self.subTest(discovery=bad), patch.object(live_smoke, "_probe", side_effect=malformed_discovery):
                calls.clear()
                self.assertEqual(expected_failure, run_smoke("auto"))
                self.assertEqual(["figma-smoke-verdict"], calls)
        raw_summary = "{truncated"
        errors = []
        calls.clear()
        for backend in ("python", "auto"):
            with self.assertRaises(json.JSONDecodeError) as exc:
                run_smoke(backend)
            errors.append(str(exc.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(["figma-smoke-file-result"], calls)

    def test_file_smoke_rejects_symlink_and_fifo_without_waiting_for_writer(self):
        import live_smoke

        root = self.base / "bundle"
        path = root / "summary/design-summary.json"
        path.parent.mkdir(parents=True)
        self.summary.write_text(json.dumps(_valid_summary()))
        real_run = subprocess.run

        def require_decline(*args, **kwargs):
            result = real_run(*args, **kwargs)
            self.assertEqual((125, b"", b""), (result.returncode, result.stdout, result.stderr))
            return result

        with patch.dict(os.environ, self.env, clear=True):
            for kind in ("symlink", "fifo"):
                with self.subTest(kind=kind):
                    if kind == "symlink":
                        path.symlink_to(self.summary)
                    else:
                        os.mkfifo(path)
                    with patch.object(subprocess, "run", side_effect=require_decline) as launched:
                        self.assertIsNone(live_smoke._bundle_receipt("figma-smoke-file-result", root, False, 1, {}))
                    self.assertEqual(1, launched.call_count)
                    path.unlink()

    def test_native_frame_headers_rounding_order_and_declines(self):
        import live_smoke

        root = self.base / "bundle"
        frames_dir = root / "frames"
        frames_dir.mkdir(parents=True)
        for name, dimensions in [("a", (3, 1)), ("b", None), ("c", (0, 1)), ("d", (2, 4))]:
            header = b"not-png" if dimensions is None else (
                b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", *dimensions))
            (frames_dir / (name + ".png")).write_bytes(header)
        frames = sorted(frames_dir.glob("*.png"))
        screens = [{"id": item, "imagePath": f"frames/{item}.png", "width": 3.5, "height": 2.5}
                   for item in ("a", "d")]
        summary = {"screens": screens}
        with patch.dict(os.environ, {**self.env, "MORU_LAUNCHER_BACKEND": "python"}, clear=True):
            expected = live_smoke._frame_failures(summary, root, frames, 1.0)
        self.assertEqual(["invalid PNG: b.png", "empty PNG dimensions: c.png (0, 1)",
                          "frame scale mismatch for d: actual=(2, 4) expected=(4, 2)"], expected)
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(live_smoke, "_png_size", side_effect=AssertionError("Python read PNG")):
                self.assertEqual(expected, live_smoke._frame_failures(summary, root, frames, 1.0))
            for malformed in ({"failures": "wrong"}, {"failures": [False]}, {"failures": [], "extra": 7}):
                with self.subTest(reply=malformed), patch.object(live_smoke, "_probe", return_value=malformed):
                    self.assertEqual(expected, live_smoke._frame_failures(summary, root, frames, 1.0))
            outside = self.base / "outside.png"
            outside.write_bytes(frames[0].read_bytes())
            (frames_dir / "link.png").symlink_to(outside)
            os.mkfifo(frames_dir / "pipe.png")
            request = {"bundle_root": str(root), "frames": [], "screens": [], "scale": 1.0}
            for path in ("../outside.png", str(outside), "frames/link.png", "frames/pipe.png"):
                with self.subTest(path=path):
                    self.assertIsNone(live_smoke._probe("figma-smoke-frames", {**request, "frames": [path]},
                                                        live_smoke.__file__))

    def test_imported_schema_falls_back_for_non_json_objects_and_bad_replies(self):
        import figma_summary_validate as schema

        summary = _valid_summary()
        summary["meta"]["fileKey"] = ""
        with patch.dict(os.environ, self.env, clear=True):
            for value in (("tuple",), {1, 2}):
                summary["extra"] = value
                with patch.object(subprocess, "run", side_effect=AssertionError("unsafe value sent")):
                    self.assertEqual(["meta.fileKey missing"], schema.validate_summary(summary))
                self.assertIs(value, summary["extra"])
            del summary["extra"]
            for malformed in (None, {"problems": "oops"}, {"problems": [None]}, {"problems": [], "extra": 0}):
                with self.subTest(reply=malformed), patch.object(schema, "_probe", return_value=malformed):
                    self.assertEqual(["meta.fileKey missing"], schema.validate_summary(summary))

    def test_large_plain_summaries_use_actual_schema_and_smoke_probes(self):
        import figma_summary_validate as schema
        import live_smoke

        real_run = subprocess.run
        calls = []

        def observe(argv, **kwargs):
            calls.append((argv[-1], len(kwargs["input"])))
            return real_run(argv, **kwargs)

        for size in (45_000, 600 * 1024):
            with self.subTest(size=size), patch.dict(os.environ, self.env, clear=True), patch.object(
                schema, "_validate_summary_reference", side_effect=AssertionError("unexpected Python fallback")
            ), patch.object(subprocess, "run", side_effect=observe):
                summary = _valid_summary()
                summary["extra"] = "a" * size
                calls.clear()
                self.assertEqual([], schema.validate_summary(summary))
                self.assertEqual([], live_smoke._native_analysis(summary)["problems"])
                self.assertEqual(["figma-summary-schema", "figma-smoke-analysis"], [name for name, _ in calls])
                self.assertTrue(all(size < wire_size <= 1024 * 1024 for _, wire_size in calls))

    def test_escaped_wire_overflow_and_custom_values_decline_before_process(self):
        import figma_summary_validate as schema
        import live_smoke

        class OpaqueDict(dict):
            def forbidden(self, *args):
                raise AssertionError("custom object protocol was invoked")

            __iter__ = __len__ = __bool__ = __repr__ = __str__ = items = forbidden

        escaped = "\\" * 285_000
        text = json.dumps({"extra": escaped})
        self.assertLess(len(text), 1024 * 1024)
        self.assertGreater(len(json.dumps({"text": text})), 1024 * 1024)
        with patch.dict(os.environ, self.env, clear=True), patch.object(
            subprocess, "run", side_effect=AssertionError("declined input was transmitted")
        ):
            for value in (escaped, OpaqueDict()):
                summary = _valid_summary()
                summary["extra"] = value
                self.assertEqual([], schema.validate_summary(summary))
                self.assertIsNone(live_smoke._native_analysis(summary))
                self.assertIs(value, summary["extra"])

    def test_hidden_node_leaks_and_inventory_disagreement(self):
        base = _valid_v4_summary()
        variants = [base]
        for key in ("assetCandidates", "flowEdges", "flowInteractions", "components"):
            value = {"id": "1:2", "fromNodeId": "1:2", "componentId": "C",
                     "instanceNodeIds": ["1:2"], "usageCount": 1}
            item = copy.deepcopy(base)
            item[key] = [value]
            variants.append(item)
        for rendered in (["1:1", "1:2"], [], ["missing"], [None, {}, "1:1"]):
            item = copy.deepcopy(base)
            item["implementationInventory"]["renderedNodeIds"] = rendered
            variants.append(item)
        for payload in variants:
            with self.subTest(payload=payload):
                self.parity(payload)

    def test_rich_coverage_deduplicates_first_asset_and_keeps_warning_overlap(self):
        payload = _valid_summary()
        payload.update(
            components=[{"componentId": "C", "usageCount": 2 ** 160, "variantProperties": [1]},
                        {"componentId": "D", "usageCount": -(2 ** 160) + 9}],
            componentBlueprints=[{"componentId": "C", "structure": []}],
            assetCandidates=[{"id": "a", "imageRefs": [1]}, {"id": "a", "assetPath": "ignored"},
                             {"id": "b", "assetPath": "b.svg", "imageRefs": [2],
                              "renderFallbackIds": [1], "nearestComponentName": "Icon"}],
            assetInventory=[{"dedupKey": "b", "usageCount": 2, "nameUnclear": True,
                             "nearestComponentName": "Icon"}],
            layoutNodes=[{"id": "n", "type": "FRAME", "opacity": 0, "strokeWeight": 0,
                          "rotation": False, "absoluteRenderBounds": {}, "constraints": []}],
            designTokens={"variables": {"variables": [None, {}]}},
            warnings=["Variables not renderable standalone", "variables", 7],
        )
        self.parity(payload)

    def test_required_container_shapes(self):
        base = _valid_summary()
        for key in base:
            for value in (None, True, 2, "wrong", {}, []):
                payload = copy.deepcopy(base)
                payload[key] = value
                with self.subTest(key=key, value=value):
                    self.parity(payload)

    def test_layout_fields_numbers_and_hex_boundaries(self):
        values = [None, False, -1, 0, 1, 1.001, 1.002, 2 ** 200, -(2 ** 200),
                  float("nan"), float("inf"), "1", [], {}]
        for field in ("visible", "opacity", "strokeWeight", "absoluteBoundingBox",
                      "effectiveVisible", "visibilityReasons", "renderedPaints"):
            for value in values:
                payload = _valid_v4_summary()
                payload["layoutNodes"][0][field] = value
                with self.subTest(field=field, value=value):
                    self.parity(payload)
        for hex_value in ("#AABBCC", "#AABBCCDD", "#aabbcc", "#ABCDEF\n", "#ABCDEF\n\n", 3, []):
            payload = _valid_summary()
            payload["colors"] = [{"hex": hex_value}]
            payload["gradients"] = [{"stops": [{"position": float("nan"), "hex": hex_value}]}]
            self.parity(payload)

    def test_schema_and_component_counts(self):
        for value in (None, True, False, -1, 0, 1, 4, 4.0, 2 ** 200, "4", [], {}):
            payload = _valid_summary()
            payload["schemaVersion"] = value
            with self.subTest(value=value):
                self.parity(payload)
        for counts in ([1, 2, 3], [0.5, 1.5], [True, False, None, "2"],
                       [2 ** 180, -(2 ** 180), 1], [-0.0], [1.0, 2.0]):
            payload = _valid_summary()
            payload["components"] = [{"componentId": str(i), "usageCount": n}
                                     for i, n in enumerate(counts)]
            self.parity(payload)

    def test_usage_is_argc_only(self):
        for args in ([], ["one", "two"], ["--help", "extra"]):
            expected = self.call(args, backend="python")
            self.assertEqual(2, expected.returncode)
            self.assertEqual(result(expected), result(self.call(args, PATH=str(self.empty_path))))

    def test_surrogate_and_exception_boundaries_defer_without_partial_output(self):
        cases = [b'"\\ud800"']
        for value in ([], {}):
            payload = _valid_v4_summary()
            payload["assetCandidates"] = [{"id": value}]
            cases.append(json.dumps(payload).encode())
        for content in cases:
            self.summary.write_bytes(content)
            self.assert_deferred([str(self.summary)])

    def assert_deferred(self, args):
        expected = self.call(args, backend="python")
        self.assertEqual(result(expected), result(self.call(args)))
        absent = self.call(args, PATH=str(self.empty_path))
        self.assertEqual(127, absent.returncode)
        self.assertEqual(b"", absent.stdout)

    def test_environment_and_source_selection_remain_authoritative(self):
        self.summary.write_text(json.dumps(_valid_summary()))
        for overrides in ({"PYTHONVERBOSE": "1"}, {"MORU_HOME": str(self.project)}):
            done = self.call([str(self.summary)], PATH=str(self.empty_path), **overrides)
            self.assertEqual(127, done.returncode)
            self.assertEqual(b"", done.stdout)

    def test_rounding_sensitive_and_nonfinite_sums_match_without_python(self):
        cases = [[1e16, 1.0, 1.0], [float("nan")], [float("inf")], [2 ** 160, 0.5],
                 [1e16, 1.0, -1e16], [1e308, 1e308, -1e308],
                 [float("inf"), -float("inf")], [-0.0, -0.0],
                 [1.0, 2 ** 160], [2 ** 160 + 1, -(2 ** 160), 0.5],
                 [2 ** 63 - 1, 1, -2 ** 63, 0.5], [5e-324] * 5,
                 [0.1] * 10, [1e308, 1.0, -1e308, 1.0]]
        rng = random.Random(4815)
        values = [0.1, 0.5, 1e16, -1e16, 5e-324, 2 ** 65, -(2 ** 65), 1.0, -0.0, 1e308]
        cases.extend([[rng.choice(values) for _ in range(12)] for _ in range(24)])
        for counts in cases:
            payload = _valid_summary()
            payload["components"] = [{"componentId": str(i), "usageCount": value}
                                     for i, value in enumerate(counts)]
            with self.subTest(counts=counts):
                self.parity(payload)

    def test_integer_to_float_overflow_still_preserves_exception_fallback(self):
        for counts in ([10 ** 400, 0.5], [0.5, 10 ** 400]):
            payload = _valid_summary()
            payload["components"] = [{"componentId": str(i), "usageCount": value}
                                     for i, value in enumerate(counts)]
            self.summary.write_text(json.dumps(payload))
            self.assert_deferred([str(self.summary)])

    def test_file_read_errors_match_without_python(self):
        self.summary.write_text("{}")
        loop = self.base / "loop"
        loop.symlink_to(loop.name)
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "missing-target")
        paths = [str(self.base / "missing"), str(self.base), "--help", "", ".",
                 "missing 한글'\n\u200b", str(self.summary / "child"), str(loop),
                 str(dangling), str(self.base / ("a" * 300)), str(self.summary) + "/"]
        denied = self.base / "denied"
        denied.write_text("{}")
        denied.chmod(0)
        self.addCleanup(denied.chmod, 0o600)
        if os.geteuid() != 0:
            paths.append(str(denied))
        for path in paths:
            with self.subTest(path=path):
                expected = self.call([path], backend="python")
                self.assertEqual(2, expected.returncode, expected.stderr)
                self.assertEqual(result(expected), result(self.call([path], PATH=str(self.empty_path))))

    def test_no_token_no_python_locale_and_regular_symlink(self):
        self.summary.write_text(json.dumps(_valid_summary()))
        linked = self.base / "linked-summary"
        linked.symlink_to(self.summary)
        for locale in ("C", "POSIX"):
            overrides = {"PYTHONUTF8": None, "LC_ALL": locale, "LANG": locale}
            expected = self.call([str(linked)], backend="python", **overrides)
            actual = self.call([str(linked)], PATH=str(self.empty_path), **overrides)
            self.assertEqual(result(expected), result(actual))
        done = self.call([str(linked)], PATH=str(self.empty_path), PYTHONIOENCODING="ascii")
        self.assertEqual(127, done.returncode)
        self.assertEqual(b"", done.stdout)

    def test_fifo_declines_without_consuming_or_waiting(self):
        fifo = self.base / "summary-fifo"
        os.mkfifo(fifo)
        done = self.call([str(fifo)], PATH=str(self.empty_path))
        self.assertEqual(127, done.returncode)
        self.assertEqual(b"", done.stdout)

    def test_descriptor_input_preserves_offset_when_native_declines(self):
        self.summary.write_bytes(b"x" + json.dumps(_valid_summary()).encode())
        linked = self.base / "descriptor-summary"
        linked.symlink_to("/dev/fd/0")
        for path in ("/dev/fd/0", str(linked)):
            outputs = []
            offsets = []
            for backend in ("python", "auto"):
                with self.summary.open("rb") as incoming:
                    incoming.seek(1)
                    done = subprocess.run([str(self.entry), "figma-validate", path],
                        stdin=incoming, capture_output=True, cwd=self.project,
                        env={**self.env, "MORU_LAUNCHER_BACKEND": backend}, timeout=20)
                    outputs.append(result(done))
                    offsets.append(incoming.tell())
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(offsets[0], offsets[1])
            with self.summary.open("rb") as incoming:
                incoming.seek(1)
                absent = subprocess.run([str(self.entry), "figma-validate", path],
                    stdin=incoming, capture_output=True, cwd=self.project,
                    env={**self.env, "PATH": str(self.empty_path)}, timeout=20)
                self.assertEqual(127, absent.returncode)
                self.assertEqual(b"", absent.stdout)
                self.assertEqual(1, incoming.tell())

    def test_source_byte_drift_declines_native(self):
        source = copied_build_root(self.base / "source")
        shutil.copytree(PROJECT / "scripts", source / "scripts", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("AGENTS.md", "index.md"):
            shutil.copy2(PROJECT / name, source / name)
        isolated = self.base / "isolated"
        isolated.mkdir()
        entry, project = prepare(isolated, source)
        self.summary.write_text(json.dumps(_valid_summary()))
        env = {**environment(isolated, source), "PATH": str(self.empty_path)}
        args = [str(entry), "figma-validate", str(self.summary)]
        before = subprocess.run(args, cwd=project, env=env, capture_output=True, timeout=20)
        self.assertEqual(0, before.returncode, before.stderr)
        smoke_args = [str(entry), "figma-live-smoke"]
        smoke_env = {k: v for k, v in env.items() if k not in ("FIGMA_TOKEN", "FIGMA_SMOKE_URL")}
        smoke_before = subprocess.run(smoke_args, cwd=project, env=smoke_env, capture_output=True, timeout=8)
        self.assertEqual(0, smoke_before.returncode, smoke_before.stderr)
        smoke_script = source / "scripts/figma-handoff/live_smoke.py"
        with smoke_script.open("ab") as changed:
            changed.write(b"\n# synthetic source drift\n")
        smoke_decline = subprocess.run(smoke_args, cwd=project, env=smoke_env, capture_output=True, timeout=8)
        self.assertEqual((127, b""), (smoke_decline.returncode, smoke_decline.stdout))
        shutil.copy2(PROJECT / "scripts/figma-handoff/live_smoke.py", smoke_script)

        # Record the real binary's decision, distinguishing a successful probe
        # from the same report printed by the Python fallback after a decline.
        executable = entry.with_name("moru-hook-native")
        real = executable.with_name("original-native")
        executable.rename(real)
        log = isolated / "probes"
        executable.write_text(f'#!/bin/sh\n{shlex.quote(str(real))} "$@"\nstatus=$?\n'
                              f'printf "%s %s\\n" "$3" "$status" >> {shlex.quote(str(log))}\nexit "$status"\n')
        executable.chmod(0o700)
        script = source / "scripts/figma-handoff/figma_validate.py"
        command = [sys.executable, "-B", str(script), str(self.summary)]

        def direct_parity(expected_code, probe_status, invocation=command):
            log.write_text("")
            original_input = self.summary.read_bytes()
            reference = subprocess.run(invocation, cwd=project, env={**env, "MORU_LAUNCHER_BACKEND": "python"},
                                       capture_output=True, timeout=20)
            self.assertEqual("", log.read_text())
            actual = subprocess.run(invocation, cwd=project, env=env, capture_output=True, timeout=20)
            self.assertEqual(expected_code, actual.returncode, actual.stderr)
            self.assertEqual(result(reference), result(actual))
            self.assertEqual([f"figma-validate-cli {probe_status}"], log.read_text().splitlines())
            self.assertEqual(original_input, self.summary.read_bytes())

        for raw, code in ((self.summary.read_bytes(), 0), (b"null", 1), (b"{", 2)):
            with self.subTest(raw=raw[:12]):
                self.summary.write_bytes(raw)
                direct_parity(code, 0)
        self.summary.write_text(json.dumps(_valid_summary()))
        changed_limit = ("import os,runpy,sys; sys.setrecursionlimit(sys.getrecursionlimit()+1); "
                         "sys.argv=sys.argv[1:]; sys.path.insert(0,os.path.dirname(sys.argv[0])); "
                         "runpy.run_path(sys.argv[0],run_name='__main__')")
        direct_parity(0, 125, [sys.executable, "-B", "-c", changed_limit, str(script), str(self.summary)])

        pointer = entry.parent.parent / "moru-root"
        original_pointer = pointer.read_bytes()
        pointer.write_text(str(PROJECT))
        try:
            direct_parity(0, 125)
        finally:
            pointer.write_bytes(original_pointer)
        policy = source / "scripts/figma-handoff/figma_summary_validate.py"
        policy.write_bytes(policy.read_bytes() + b"\n# changed contract\n")
        direct_parity(0, 125)
        after = subprocess.run(args, cwd=project, env=env, capture_output=True, timeout=20)
        self.assertEqual(127, after.returncode)
        self.assertEqual(b"", after.stdout)


if __name__ == "__main__":
    unittest.main()
