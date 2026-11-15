"""Transported read-only retention snapshots; only the harness writes fixtures."""
import hashlib
import json
import subprocess
import sys


def check_retention(native, entry, base, project, env):
    directory = base / "retention snapshot"
    directory.mkdir()
    target = directory / "run-registry.json"
    options = {"state_dir": str(directory), "states": ["running", "completed"],
               "int_digits": getattr(sys, "get_int_max_str_digits", lambda: 0)()}
    cases = [('{"schema_version":true,"runs":[{"run_id":"z","state":"running"},{"run_id":"a","state":"completed"}],"extra":NaN}', [["z","running"],["a","completed"]]),
             ('{"schema_version":1,"runs":[]}', []),
             ('{"schema_version":1,"runs":[{"run_id":"x","state":"unknown"}]}', None),
             ('{"schema_version":1,"runs":[{"run_id":"x","state":"running"},{"run_id":"x","state":"running"}]}', None)]
    for text, expected in cases:
        target.write_text(text, encoding="utf-8")
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        done = subprocess.run([str(native),str(entry),"--registry-read-probe","retention-states"],
            input=json.dumps(options).encode(),env=env,cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"value":expected}},done
        assert before==hashlib.sha256(target.read_bytes()).hexdigest()
        assert [p.name for p in directory.iterdir()]==[target.name]
    for payload in ({**options,"extra":1},{**options,"int_digits":options["int_digits"]+1}):
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-states"],
            input=json.dumps(payload).encode(),env={**env,"MORU_HOOK_SOFT_FAIL":"1"},cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stdout,done.stderr)==(125,b"",b""),done
    return 6
