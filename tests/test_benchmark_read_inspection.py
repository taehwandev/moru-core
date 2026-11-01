"""A redirected parent bytecode cache must not invalidate the warm control."""
from pathlib import Path
import tempfile
import sys
import subprocess
import unittest
from unittest.mock import patch

from read_inspection_support import cache_hashes, prepare_cache
from native_pretool_support import environment


class ReadInspectionBenchmarkTests(unittest.TestCase):
    def test_preparation_uses_the_actual_callback_environment_and_finds_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "source"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts/sample.py").write_text("value = 1\n")
            redirected = base / "redirected"
            envs = {v: environment(base, root) for v in ("reference", "candidate")}
            entries = {v: Path(sys.executable) for v in envs}
            cases = [("native_cat_control", ["-c", f"import sys; sys.path.insert(0, {str(root / 'scripts')!r}); import sample"], b"")]
            with patch.dict("os.environ", {"PYTHONPYCACHEPREFIX": str(redirected)}):
                prepare_cache(base, entries, envs, cases, root)
            hashes = cache_hashes(base)
            self.assertTrue(all(hashes.values()))
            self.assertTrue(all("sample.cpython" in str(files) for files in hashes.values()))
            self.assertFalse(redirected.exists())

    def test_successful_process_without_cache_files_is_not_preparation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            entries = {v: Path(sys.executable) for v in ("reference", "candidate")}
            envs = {v: {} for v in entries}
            cases = [("native_cat_control", [], b"")]
            done = subprocess.CompletedProcess([], 0, b"", b"")
            with patch("read_inspection_support.subprocess.run", return_value=done):
                with self.assertRaisesRegex(RuntimeError, "produced no caches"):
                    prepare_cache(base, entries, envs, cases, base)
