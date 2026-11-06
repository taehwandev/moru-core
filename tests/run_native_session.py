#!/usr/bin/env python3
"""Give conformance fixtures a live POSIX session leader and stable owner.

Hosted runners may inherit a session whose leader already exited. Keep this
parent alive while the test command owns a fresh session, so Python and native
subprocesses resolve the same real owner without mocking process identity.
"""
import subprocess
import sys


if __name__ == "__main__":
    result = subprocess.run([sys.executable, "-B", *sys.argv[1:]], start_new_session=True)
    raise SystemExit(result.returncode if result.returncode >= 0 else 128 - result.returncode)
