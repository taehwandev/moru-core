"""Backups read protected sources; their destinations retain write protection."""

import shlex
import io
import tempfile
import subprocess
import tarfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import claude_pretool_gate as gate
from test_claude_bash_paths import _opt_in_project, _require_linked_worktree


class ArchivePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.source = _opt_in_project(base / "source")
        self.destination = _opt_in_project(base / "destination")
        _require_linked_worktree(self.source)
        _require_linked_worktree(self.destination)
        self.cwd = base / "scratch"
        self.cwd.mkdir()

    def roots(self, command):
        return gate.bash_target_project_roots(shlex.split(command), self.cwd)

    def test_tar_create_reads_its_change_directory_and_members(self):
        command = f"tar -cf {self.destination}/backup.tar -C {self.source} local.properties config"
        self.assertEqual([self.destination], self.roots(command))

    def test_tar_create_reads_absolute_source_members(self):
        command = f"tar -czf {self.destination}/backup.tar.gz {self.source}/config"
        self.assertEqual([self.destination], self.roots(command))

    def test_plain_ditto_reads_source_and_protects_destination(self):
        command = f"ditto {self.source}/config {self.destination}/config"
        self.assertEqual([self.destination], self.roots(command))

    def test_a_scratch_backup_is_admitted_without_a_write_run_for_its_source(self):
        for command in (f"tar -cf {self.cwd}/backup.tar -C {self.source} config",
                        f"ditto {self.source}/config {self.cwd}/config"):
            with self.subTest(command=command):
                output = io.StringIO()
                with redirect_stdout(output):
                    verdict = gate._decide({"tool_name": "Bash", "cwd": str(self.cwd),
                        "session_id": "backup-session", "tool_input": {"command": command}})
                self.assertEqual(0, verdict)
                self.assertEqual("", output.getvalue())

    def test_reverse_copy_still_protects_the_source_project_as_destination(self):
        command = f"ditto {self.destination}/config {self.source}/config"
        self.assertEqual([self.source], self.roots(command))

    def test_admitted_backup_really_preserves_local_files_in_an_archive(self):
        source = self.source / "config"
        source.write_bytes(b"local fixture data\n")
        archive = self.cwd / "backup.tar"
        command = ["tar", "-cf", str(archive), "-C", str(self.source), "config"]
        self.assertNotIn(self.source, gate.bash_target_project_roots(command, self.cwd))
        subprocess.run(command, check=True, capture_output=True)
        with tarfile.open(archive) as saved:
            self.assertEqual(source.read_bytes(), saved.extractfile("config").read())
        self.assertEqual(b"local fixture data\n", source.read_bytes())

    def test_unmodelled_archive_modes_and_options_keep_all_paths(self):
        for flags in ("-xf", "--remove-files -cf", "-cf --checkpoint-action=exec=sh"):
            with self.subTest(flags=flags):
                roots = self.roots(f"tar {flags} {self.destination}/a.tar -C {self.source} config")
                self.assertIn(self.source, roots)

    def test_source_exemption_never_covers_a_later_write(self):
        command = f"tar -cf {self.cwd}/backup.tar -C {self.source} config && touch {self.source}/new"
        self.assertIn(self.source, self.roots(command))

    def test_redirections_and_untrusted_executables_keep_source_protection(self):
        for command in (
            f"tar -cf {self.cwd}/a.tar {self.source}/config > {self.source}/log",
            f"{self.cwd}/tar -cf {self.cwd}/a.tar {self.source}/config",
            f"ditto --unknown {self.source}/config {self.destination}/config",
        ):
            with self.subTest(command=command):
                self.assertIn(self.source, self.roots(command))

    def test_inherited_tar_options_and_relative_archive_destinations_are_not_exempted(self):
        with patch.dict("os.environ", {"TAR_OPTIONS": "--remove-files"}):
            self.assertIn(self.source, self.roots(f"tar -cf {self.cwd}/a.tar {self.source}/config"))
        self.assertIn(self.source, self.roots(f"tar -cf relative.tar -C {self.source} config"))
