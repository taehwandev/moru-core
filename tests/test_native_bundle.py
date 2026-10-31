"""Portable artifact transport rejects stale or unsafe archives before writes."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from support import native_bundle as bundle
from support.native_launcher_install import artifact_plan


class NativeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-bundle-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.target = self.base / "target"
        for root in (self.source, self.target):
            package = root / "native/checkout-identity"
            (package / "src").mkdir(parents=True)
            for name in ("Cargo.toml", "Cargo.lock", "src/main.rs"):
                (package / name).write_text("same source\n")
        state = self.source / ".moru/native"
        (state / "bin").mkdir(parents=True)
        records = []
        for name in bundle._BINARIES:
            path = state / "bin" / name
            path.write_bytes(name.encode())
            path.chmod(0o755)
            records.append({"binary": str(path), "bytes": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        receipt = {**records[0], "launcher": records[1], "rustc": "rustc fixture",
                   "source_sha256": bundle._sources(self.source)}
        (state / "build.json").write_text(json.dumps(receipt))
        self.archive = self.base / "runtime.tar.gz"
        bundle.pack_bundle(self.source, self.archive)

    def contents(self):
        with tarfile.open(self.archive) as archive:
            return [(member.name, archive.extractfile(member).read()) for member in archive]

    def rewrite(self, rows):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data in rows:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def edit_manifest(self, update):
        rows = self.contents()
        value = json.loads(rows[0][1])
        update(value)
        rows[0] = ("manifest.json", json.dumps(value).encode())
        self.rewrite(rows)

    def reject_preserving_target(self):
        state = self.target / ".moru/native"
        (state / "bin").mkdir(parents=True, exist_ok=True)
        receipt = state / "build.json"
        receipt.write_bytes(b"old receipt")
        binary = state / "bin" / bundle._BINARIES[0]
        binary.write_bytes(b"old binary")
        before = {str(p.relative_to(self.target)): p.read_bytes()
                  for p in self.target.rglob("*") if p.is_file()}
        with self.assertRaises((OSError, ValueError)):
            bundle.install_bundle(self.target, self.archive)
        self.assertEqual(before, {str(p.relative_to(self.target)): p.read_bytes()
                                 for p in self.target.rglob("*") if p.is_file()})

    def test_roundtrip_works_with_existing_installer_without_toolchain(self):
        with patch.dict(os.environ, {"PATH": ""}):
            result = bundle.install_bundle(self.target, self.archive)
        state = self.target / ".moru/native"
        self.assertEqual(result, json.loads((state / "build.json").read_text()))
        for name in bundle._BINARIES:
            path = state / "bin" / name
            self.assertEqual(name.encode(), path.read_bytes())
            self.assertEqual(0o755, path.stat().st_mode & 0o777)
        self.assertIsNotNone(artifact_plan(self.target, self.base / "home/bin/moru-hook"))

    def test_wrong_host_and_source_rejected_before_writes(self):
        original = self.archive.read_bytes()
        for field, value in (("platform", {"os": "other", "arch": "arm64"}),
                             ("source_sha256", {}), ("schema_version", True)):
            with self.subTest(field=field):
                self.archive.write_bytes(original)
                self.edit_manifest(lambda manifest: manifest.update({field: value}))
                self.reject_preserving_target()

    def test_corrupt_binary_and_stale_target_source_rejected(self):
        rows = self.contents()
        rows[1] = (rows[1][0], b"corrupted")
        self.rewrite(rows)
        self.reject_preserving_target()
        bundle.pack_bundle(self.source, self.archive)
        (self.target / "native/checkout-identity/src/main.rs").write_text("new source")
        self.reject_preserving_target()

    def test_unsafe_duplicate_extra_and_missing_members_rejected(self):
        original = self.contents()
        for rows in (original + [("../outside", b"bad")], original + [original[0]],
                     original + [("extra", b"bad")], original[:-1]):
            with self.subTest(names=[row[0] for row in rows]):
                self.rewrite(rows)
                self.reject_preserving_target()
        self.assertFalse((self.base / "outside").exists())

    def test_links_and_expansion_limits_rejected(self):
        original = self.archive.read_bytes()
        with tarfile.open(self.archive, "w:gz") as archive:
            info = tarfile.TarInfo("manifest.json")
            info.type, info.linkname = tarfile.SYMTYPE, "outside"
            archive.addfile(info)
        self.reject_preserving_target()
        self.archive.write_bytes(original)
        with patch.object(bundle, "_MAX_BYTES", 128):
            self.reject_preserving_target()
        # Compressed bytes fit, but even ignored tar padding/headers exceed
        # the expansion bound before tar parsing can allocate from them.
        with patch.object(bundle, "_MAX_BYTES", 4096):
            self.reject_preserving_target()
        with patch.object(bundle, "_MAX_MANIFEST", 10):
            self.reject_preserving_target()

    def test_malformed_and_duplicate_json_rejected(self):
        original = self.contents()
        for data in (b"not json", b"[]", b'{"schema_version":1,"schema_version":1}'):
            self.rewrite([("manifest.json", data), *original[1:]])
            self.reject_preserving_target()

    def test_pack_refuses_stale_receipt_and_retains_existing_archive(self):
        original = self.archive.read_bytes()
        (self.source / "native/checkout-identity/Cargo.lock").write_text("changed")
        with self.assertRaisesRegex(ValueError, "sources"):
            bundle.pack_bundle(self.source, self.archive)
        self.assertEqual(original, self.archive.read_bytes())

    def test_symlink_installation_root_rejected(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (self.target / ".moru").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            bundle.install_bundle(self.target, self.archive)
        self.assertEqual([], list(elsewhere.iterdir()))

    def test_cli_install_reports_success_without_compiler_or_global_changes(self):
        cli = Path(__file__).resolve().parents[1] / "scripts/native-runtime-bundle.py"
        done = subprocess.run([sys.executable, "-B", str(cli), "install", "--bundle", str(self.archive),
                               "--root", str(self.target)], env=dict(os.environ, PATH=""),
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertEqual("rustc fixture", json.loads(done.stdout)["rustc"])

    def test_publication_failure_retires_old_receipt(self):
        bundle.install_bundle(self.target, self.archive)
        original = Path.replace
        def fail_first_binary(path, target):
            if path.name == bundle._BINARIES[0] and path.parent.name.startswith(".native-install-"):
                raise OSError("injected replacement failure")
            return original(path, target)
        with patch.object(Path, "replace", fail_first_binary):
            with self.assertRaisesRegex(OSError, "injected"):
                bundle.install_bundle(self.target, self.archive)
        self.assertFalse((self.target / ".moru/native/build.json").exists())
        self.assertIsNone(artifact_plan(self.target, self.base / "home/bin/moru-hook"))


if __name__ == "__main__":
    unittest.main()
