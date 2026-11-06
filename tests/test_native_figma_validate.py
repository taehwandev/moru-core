"""Offline Figma validator: exact reference output, refusals and no-Python proof."""
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

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

    def test_file_json_and_exception_boundaries_defer_without_partial_output(self):
        cases = [b"{", b'"\\ud800"', b"\xff", b"\xef\xbb\xbf{}"]
        for value in ([], {}):
            payload = _valid_v4_summary()
            payload["assetCandidates"] = [{"id": value}]
            cases.append(json.dumps(payload).encode())
        for content in cases:
            self.summary.write_bytes(content)
            self.assert_deferred([str(self.summary)])
        for args in ([str(self.base / "missing")], [str(self.base)], ["--help"]):
            self.assert_deferred(args)

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

    def test_rounding_sensitive_and_nonfinite_sums_defer(self):
        for counts in ([1e16, 1.0, 1.0], [float("nan")], [float("inf")],
                       [2 ** 160, 0.5]):
            payload = _valid_summary()
            payload["components"] = [{"componentId": str(i), "usageCount": value}
                                     for i, value in enumerate(counts)]
            self.summary.write_text(json.dumps(payload))
            self.assert_deferred([str(self.summary)])

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
        policy = source / "scripts/figma-handoff/figma_summary_validate.py"
        policy.write_bytes(policy.read_bytes() + b"\n# changed contract\n")
        after = subprocess.run(args, cwd=project, env=env, capture_output=True, timeout=20)
        self.assertEqual(127, after.returncode)
        self.assertEqual(b"", after.stdout)


if __name__ == "__main__":
    unittest.main()
