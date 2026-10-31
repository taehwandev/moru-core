"""Build failures must retain the last working native executable."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build_native_runtime as builder


class BuildNativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="checkout-build-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.package = self.root / "native/checkout-identity"
        (self.package / "src").mkdir(parents=True)
        for name in ("Cargo.toml", "Cargo.lock", "src/main.rs"):
            (self.package / name).write_text("fixture\n")
        self.state = self.root / ".moru/native"
        self.binary = self.state / "bin" / builder.NAME
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"last working executable")
        for key, value in (("PROJECT", self.root), ("PACKAGE", self.package), ("STATE", self.state)):
            patcher = patch.object(builder, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_toolchain_never_installs_or_replaces(self):
        with patch.object(builder.shutil, "which", return_value=None), patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "no tools are installed"):
                builder.build()
        run.assert_not_called()
        self.assertEqual(b"last working executable", self.binary.read_bytes())

    def test_compile_failure_retains_last_binary(self):
        with patch.object(builder.shutil, "which", return_value="/tool"), \
                patch.object(builder.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "cargo")):
            with self.assertRaises(subprocess.CalledProcessError):
                builder.build()
        self.assertEqual(b"last working executable", self.binary.read_bytes())

    def test_invalid_generated_executable_retains_last_binary(self):
        with patch.object(builder.shutil, "which", return_value="/tool"), \
                patch.object(builder.subprocess, "run", side_effect=[None, subprocess.CalledProcessError(7, "binary")]):
            with self.assertRaises(subprocess.CalledProcessError):
                builder.build()
        self.assertEqual(b"last working executable", self.binary.read_bytes())

    def test_success_is_offline_locked_and_publishes_executable_with_receipt(self):
        artifact = self.state / "cargo-target/release" / builder.NAME
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"new executable")
        (artifact.parent / builder.LAUNCHER_NAME).write_bytes(b"native launcher executable")
        with patch.object(builder.shutil, "which", return_value="/tool"), \
                patch.object(builder.subprocess, "run") as run, \
                patch.object(builder.subprocess, "check_output", return_value="rustc fixture\n"):
            receipt = builder.build()
        args = run.call_args_list[0].args[0]
        self.assertIn("--offline", args)
        self.assertIn("--locked", args)
        self.assertEqual(b"new executable", self.binary.read_bytes())
        self.assertEqual(0o755, self.binary.stat().st_mode & 0o777)
        self.assertEqual(receipt, json.loads((self.state / "build.json").read_text()))
        self.assertEqual(3, len(receipt["source_sha256"]))
        self.assertEqual(b"native launcher executable", (self.state / "bin" / builder.LAUNCHER_NAME).read_bytes())
        self.assertEqual([], list(self.binary.parent.glob(".checkout-*")))

    def test_launcher_probe_failure_retains_previous_checkout_binary(self):
        with patch.object(builder.shutil, "which", return_value="/tool"), \
                patch.object(builder.subprocess, "run", side_effect=[None, None, subprocess.CalledProcessError(2, "launcher")]):
            with self.assertRaises(subprocess.CalledProcessError):
                builder.build()
        self.assertEqual(b"last working executable", self.binary.read_bytes())


if __name__ == "__main__":
    unittest.main()
