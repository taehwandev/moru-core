"""Portable source-bound setup text merge, with no config writes or Python PATH."""
import json
import subprocess


def check_codex_statusline(native, entry, project, env):
    default = '[tui]\nstatus_line = ["model-with-reasoning", "current-dir", "five-hour-limit", "weekly-limit"]\n'
    already = "[tui]\nstatus_line=['five-hour-limit', 'weekly-limit']"
    conflict = "[tui]\nstatus_line=[7]"
    multiline = '[tui]\nstatus_line=[\n  "한글" # keep\n]\n'
    expected = '[tui]\nstatus_line=[\n  "한글", # keep\n  "five-hour-limit", "weekly-limit"\n]\n'
    for text, status, updated in (("", "changed", default), (already, "ok", already),
                                  (conflict, "missing", conflict), (multiline, "changed", expected)):
        done = subprocess.run([str(native), str(entry), "--setup-probe", "codex-status-line"],
            input=json.dumps({"text": text}).encode(), env=env, cwd=project, capture_output=True, timeout=8)
        assert (done.returncode, done.stderr) == (0, b""), done
        assert json.loads(done.stdout) == {"schema_version": 1, "result": {"status": status, "text": updated}}, done
    for operation, payload in (("unknown", {}), ("codex-status-line", {}),
                                ("codex-status-line", {"text": 7}), ("codex-status-line", {"text": "", "extra": 1})):
        done = subprocess.run([str(native), str(entry), "--setup-probe", operation],
            input=json.dumps(payload).encode(), env={**env, "MORU_HOOK_SOFT_FAIL": "1"}, cwd=project,
            capture_output=True, timeout=8)
        assert (done.returncode, done.stdout, done.stderr) == (125, b"", b""), done
    return 8
