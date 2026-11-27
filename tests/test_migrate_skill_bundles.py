from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import migrate_skill_bundles as migration
from native_pretool_support import environment, prepare


class SkillBundleMigrationTests(unittest.TestCase):
    def test_native_discovery_and_rendering_match_reference_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            prepare(base)
            selected = ["common/alpha.md", "common/zeta.md", "workflows/publish.md",
                        "product-patterns/search.md", "platforms/android/layout.md", "docs/guide.md"]
            kept = "common/alpha.md"
            ignored = ["workflows/README.md", "common/skills/legacy/SKILL.md", "platforms/platforms.md"]
            snapshots = []
            for backend in ("python", "auto"):
                root = base / backend
                for relative in [*reversed(selected), *ignored]:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("# Sample guide\n\n한글 🧪\n", encoding="utf-8")
                asset = root / "asset.txt"
                asset.write_bytes(b"asset")
                (root / kept).write_bytes(b"# Keep\r\n\r\n[asset](../asset.txt#anchor)\r\n")
                env = {**environment(base), "MORU_LAUNCHER_BACKEND": backend, "PATH": ""}
                with patch.object(migration, "ROOT", root), patch.dict(os.environ, env, clear=True), ExitStack() as guards:
                    if backend == "auto":
                        for name in ("_source_docs_reference", "_render_reference"):
                            guards.enter_context(patch.object(migration, name, side_effect=AssertionError(name)))
                    sources = migration.source_docs()
                    self.assertEqual(selected, [path.relative_to(root).as_posix() for path in sources])
                    for path in sources:
                        migration.migrate_doc(path, keep_stub=path == root / kept)
                    migration.migrate_doc(root / kept, keep_stub=True)
                self.assertTrue((root / kept).is_file())
                self.assertTrue(all(not (root / path).exists() for path in selected if path != kept))
                snapshots.append({path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()})
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(b"# Keep\n\n[asset](../../../../asset.txt#anchor)\n",
                             snapshots[1][Path("common/skills/alpha/references/current-guidance.md")])

    def test_compact_entrypoint_keeps_detailed_rules_and_relative_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "common/testing.md"
            source.parent.mkdir()
            related = root / "example.txt"
            related.write_text("fixture", encoding="utf-8")
            source.write_text(
                "---\nstatus: stable\ntype: human-reviewed\n---\n\n"
                "# Testing\n\nStop on a failed required check.\n\n"
                "[Fixture](../example.txt)\n",
                encoding="utf-8",
            )
            with patch.object(migration, "ROOT", root):
                migration.migrate_doc(source)
            skill = root / "common/skills/testing/SKILL.md"
            reference = skill.parent / "references/current-guidance.md"
            text = skill.read_text(encoding="utf-8")
            self.assertFalse(source.exists())
            self.assertLessEqual(len(text.encode()), 650)
            self.assertIn("references/current-guidance.md", text)
            self.assertIn("stop", text)
            self.assertIn("verification before acting", text)
            self.assertIn("in-scope", text)
            detailed = reference.read_text(encoding="utf-8")
            self.assertIn("status: stable", detailed)
            self.assertIn("Stop on a failed required check.", detailed)
            self.assertIn("[Fixture](../../../../example.txt)", detailed)

    def test_named_compatibility_stub_still_resolves_to_preserved_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "common/testing.md"
            source.parent.mkdir()
            original = "# Testing\n\nDo not report an unobserved check as passed.\n"
            source.write_text(original, encoding="utf-8")
            with patch.object(migration, "ROOT", root):
                migration.migrate_doc(source, keep_stub=True)
                migration.migrate_doc(source, keep_stub=True)
            self.assertIn(migration.STUB_MARKER, source.read_text())
            reference = root / "common/skills/testing/references/current-guidance.md"
            self.assertEqual(original, reference.read_text())


if __name__ == "__main__":
    unittest.main()
