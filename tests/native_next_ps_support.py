"""Real orphaned POSIX session fixtures; never serialize inherited environments."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time

def _wait_file(path, timeout):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("dead-session fixture did not finish")
        time.sleep(0.01)


def dead_session_next(launcher, project, base, git_path, ps_body, *, env=None, input_bytes=None):
    """Return four decoded results and ps argv for a genuinely dead session leader.

    ps_body is a fixture shell body, or None for an unavailable ps executable.
    Calls are ordered JSON python/native, then Markdown python/native.
    Caller supplies an isolated environment for bundle/installation fixtures.
    """
    with tempfile.TemporaryDirectory(prefix="next-ps-", dir=base) as temporary:
        work = Path(temporary)
        if input_bytes is not None:
            (work / "input").write_bytes(input_bytes)
        binary = work / "bin"
        binary.mkdir()
        (binary / "git").symlink_to(git_path)
        python_bin = work / "python"
        python_bin.mkdir()
        (python_bin / "python3").symlink_to(sys.executable)
        if ps_body is not None:
            script = binary / "ps"
            log = shlex.quote(str(work / "argv"))
            script.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >> " + log + "\n" + ps_body + "\n")
            script.chmod(0o755)
        if env is None:
            from native_pretool_support import environment
            env = environment(base)
        inherited = dict(env)
        inherited["CODEX_THREAD_ID"] = "synthetic-next"
        process = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve()), str(work), str(launcher), str(project)],
            env=inherited, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        child_pid = None
        try:
            process.wait(timeout=5)  # Reap leader before authorizing its child to probe.
            if process.returncode != 0:
                raise AssertionError("dead-session fixture leader failed to start")
            _wait_file(work / "child", 5)
            child_pid = int((work / "child").read_text())
            if process.returncode != 0 or os.getsid(child_pid) != process.pid:
                raise AssertionError("fixture child did not retain the detached session")
            (work / "go").touch()
            _wait_file(work / "report", 40)
            report = json.loads((work / "report").read_text())
            if "error" in report:
                raise AssertionError(report["error"])
            if report["sid"] != process.pid or not report["leader_dead"]:
                raise AssertionError("fixture did not prove its session leader dead")
            for call in report["calls"]:
                for key in ("stdout", "stderr"):
                    call[key] = base64.b64decode(call[key])
            report["argv"] = (work / "argv").read_text().splitlines() if (work / "argv").exists() else []
            return report
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if child_pid is not None:
                try:
                    if os.getsid(child_pid) == process.pid:
                        os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _child(work, launcher, project):
    pid = os.fork()
    if pid:
        (work / "child").write_text(str(pid))
        os._exit(0)
    report = {}
    try:
        _wait_file(work / "go", 10)
        sid = os.getsid(0)
        try:
            os.kill(sid, 0)
            dead = False
        except ProcessLookupError:
            dead = True
        if not dead:
            raise AssertionError("leader must be reaped before probing")
        calls = []
        for output in ("json", "markdown"):
            for backend in ("python", "auto"):
                env = dict(os.environ)
                binary = str(work / "bin")
                env["PATH"] = binary + os.pathsep + str(work / "python") if backend == "python" else binary
                env["MORU_LAUNCHER_BACKEND"] = backend
                done = subprocess.run(
                    [launcher, "next", "--project", project, "--format", output],
                    env=env, cwd=project, capture_output=True, timeout=9,
                    input=(work / "input").read_bytes() if (work / "input").exists() else None,
                )
                calls.append({"returncode": done.returncode,
                    "stdout": base64.b64encode(done.stdout).decode(),
                    "stderr": base64.b64encode(done.stderr).decode()})
        report = {"sid": sid, "leader_dead": dead, "calls": calls}
    except Exception as error:
        report = {"error": type(error).__name__}
    (work / "report.tmp").write_text(json.dumps(report))
    (work / "report.tmp").replace(work / "report")
    os._exit(0)


if __name__ == "__main__":
    _child(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
