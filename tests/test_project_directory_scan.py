"""Enumeration parity, including symlinks and partial/error behavior."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_project_search import SKIP_SEARCH_DIRS, scan_project_roots
from support.project_directory_scan import child_directories


class Entry:
    def __init__(self, name, directory=True, error=None):
        self.name, self.directory, self.error = name, directory, error

    def is_dir(self, *, follow_symlinks=True):
        if self.error:
            raise self.error
        return self.directory


@contextmanager
def entries(items):
    yield iter(items)


class ProjectDirectoryScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="project-scan-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_files_hidden_names_exact_skip_set_and_order(self):
        for name in ("zebra", "Alpha", "Build", ".hidden", "node_modules", "한글"):
            (self.root / name).mkdir()
        (self.root / "middle.txt").touch()
        self.assertEqual(["Alpha", "Build", "zebra", "한글"],
                         [p.name for p in child_directories(self.root, SKIP_SEARCH_DIRS)])

    def test_relative_path_spelling_is_preserved(self):
        (self.root / "child").mkdir()
        relative = Path(os.path.relpath(self.root))
        self.assertEqual([relative / "child"], child_directories(relative, set()))
        self.assertFalse(child_directories(relative, set())[0].is_absolute())

    def test_directory_links_included_without_resolving_and_broken_links_skipped(self):
        directory = self.root / "real"
        directory.mkdir()
        file = self.root / "file"
        file.touch()
        (self.root / "directory-link").symlink_to(directory, target_is_directory=True)
        (self.root / "file-link").symlink_to(file)
        (self.root / "broken").symlink_to(self.root / "missing")
        (self.root / "self-link").symlink_to(self.root / "self-link")
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        self.assertEqual(["directory-link", "loop", "real"],
                         [p.name for p in child_directories(self.root, set())])

    def test_missing_or_file_parent_is_empty(self):
        file = self.root / "file"
        file.touch()
        for path in (self.root / "missing", file):
            self.assertEqual([], child_directories(path, set()))

    def test_enumeration_permission_error_is_empty(self):
        with patch("support.project_directory_scan.os.scandir", side_effect=PermissionError):
            self.assertEqual([], child_directories(self.root, set()))

    def test_late_iteration_error_discards_partial_results_and_closes(self):
        closed = []
        def partial():
            yield Entry("first")
            raise OSError("enumeration failed")
        @contextmanager
        def scan(_):
            try:
                yield partial()
            finally:
                closed.append(True)
        with patch("support.project_directory_scan.os.scandir", scan):
            self.assertEqual([], child_directories(self.root, set()))
        self.assertEqual([True], closed)

    def test_one_entry_error_does_not_discard_other_directories(self):
        items = [Entry("z"), Entry("unreadable", error=PermissionError()), Entry("a")]
        with patch("support.project_directory_scan.os.scandir", return_value=entries(items)):
            self.assertEqual([self.root / "a", self.root / "z"], child_directories(self.root, set()))

    def test_sort_is_stable_lower_not_casefold(self):
        items = [Entry(name) for name in ("a", "A", "İ", "i", "ß", "ss", "é", "e\u0301")]
        with patch("support.project_directory_scan.os.scandir", return_value=entries(items)):
            self.assertEqual(["a", "A", "e\u0301", "i", "İ", "ss", "ß", "é"],
                             [p.name for p in child_directories(self.root, set())])

    def test_non_oserror_is_not_swallowed(self):
        with patch("support.project_directory_scan.os.scandir", side_effect=ValueError("bad input")):
            with self.assertRaises(ValueError):
                child_directories(self.root, set())

    def test_bfs_depth_and_visit_budget_keep_the_same_prefix(self):
        for name in ("A", "B", "A/nested", ".hidden", "node_modules"):
            path = self.root / name
            path.mkdir(parents=True, exist_ok=True)
            (path / "AGENTS.md").touch()
        (self.root / "AGENTS.md").touch()
        root = self.root.resolve()
        self.assertEqual([root], list(scan_project_roots(root, max_depth=0)))
        self.assertEqual([root, root / "A", root / "B"], list(scan_project_roots(root, max_depth=1)))
        self.assertEqual([root, root / "A"], list(scan_project_roots(root, max_depth=2, max_visited=2)))
        self.assertEqual([root, root / "A", root / "B", root / "A/nested"],
                         list(scan_project_roots(root, max_depth=2)))


if __name__ == "__main__":
    unittest.main()
