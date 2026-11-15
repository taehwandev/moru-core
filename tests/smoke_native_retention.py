"""Transported read-only retention snapshots; only the harness writes fixtures."""
import hashlib
import json
import os
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


def check_retention_identity(native,entry,base,project,env):
    root=base/"retention identity";root.mkdir();(root/"a").mkdir()
    (root/"a/x").write_text("data");(root/"a-b").write_text("hyphen");(root/"한글").write_text("data")
    paths=[root,root/"a",root/"a/x",root/"a-b",root/"한글"]
    def snapshot():
        rows=[]
        for path in paths:
            metadata=os.lstat(path)
            rows.append(["." if path==root else str(path.relative_to(root)),metadata.st_dev,metadata.st_ino,
                metadata.st_mode,metadata.st_size,metadata.st_mtime_ns,metadata.st_ctime_ns])
        return rows
    expected=snapshot()
    done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-identities"],
        input=json.dumps({"paths":[str(root)]}).encode(),env=env,cwd=project,capture_output=True,timeout=8)
    assert (done.returncode,done.stderr)==(0,b""),done
    assert json.loads(done.stdout)=={"schema_version":1,"result":{"value":[expected]}},done
    assert expected==snapshot()
    for payload in ({},{"paths":[str(root)],"extra":1},{"paths":["\udcff"]},{"paths":[str(root/"absent")]}):
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-identities"],
            input=json.dumps(payload).encode(),env={**env,"MORU_HOOK_SOFT_FAIL":"1"},cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stdout,done.stderr)==(125,b"",b""),done
    return 5


def check_retention_bytes(native,entry,base,project,env):
    root=base/"retention sizes";root.mkdir();(root/"nested").mkdir()
    (root/"nested/data").write_bytes(b"12345");(root/"plain").write_bytes(b"123")
    (root/"link").symlink_to("nested/data");(root/"broken").symlink_to("absent")
    (root/"dir-link").symlink_to("nested",target_is_directory=True)
    before={str(p.relative_to(root)):os.lstat(p) for p in [root,*root.rglob("*")]}
    for paths,expected in (([root,root],"26"),([],"0"),([root/"plain"],"0")):
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-bytes"],
            input=json.dumps({"paths":[str(path) for path in paths]}).encode(),env=env,cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"value":expected}},done
    for payload in ({"paths":[str(root)],"extra":1},{"paths":[str(root/"absent")]}):
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-bytes"],
            input=json.dumps(payload).encode(),env={**env,"MORU_HOOK_SOFT_FAIL":"1"},cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stdout,done.stderr)==(125,b"",b""),done
    after={str(p.relative_to(root)):os.lstat(p) for p in [root,*root.rglob("*")]}
    assert set(before)==set(after)
    assert all((m.st_ino,m.st_mode,m.st_size,m.st_mtime_ns,m.st_ctime_ns)==
        (after[p].st_ino,after[p].st_mode,after[p].st_size,after[p].st_mtime_ns,after[p].st_ctime_ns) for p,m in before.items())
    return 5


def check_retention_plan(native,entry,base,project,env):
    root=base/"retention preview";root.mkdir()
    names=["a"*32,"b"*32]
    for index,name in enumerate(names):
        folder=root/name;folder.mkdir();(folder/"continuation.json").write_text('{"phase":"done"}')
        os.utime(folder,(100+index,100+index))
    paths=[root,*root.rglob("*")]
    def snapshot():
        return {str(p.relative_to(root)):(m.st_dev,m.st_ino,m.st_mode,m.st_size,m.st_mtime_ns,m.st_ctime_ns)
                for p in paths for m in [os.lstat(p)]}
    before=snapshot()
    options={"directory":str(root),"registry_states":None,"registry_uncertain":False,"protected":[],
        "cutoff":1000,"orphan_cutoff":1000,"keep":1,"holding_states":["running"],
        "settled_states":["completed"],"finished_phases":["done"],
        "int_digits":getattr(sys,"get_int_max_str_digits",lambda:0)()}
    cases=[(options,[names[1],names[0]],[],[names[0]]),
           ({**options,"protected":[names[0]]},[names[1]],[names[0]],[]),
           ({**options,"registry_uncertain":True},[],names,[])]
    for payload,finished,unfinished,removable in cases:
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-plan"],
            input=json.dumps(payload).encode(),env=env,cwd=project,capture_output=True,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        result=json.loads(done.stdout)["result"]["value"]
        assert result["finished"]==finished and result["unfinished"]==unfinished,result
        assert result["removable"]==removable and result["kept"]==finished[:1],result
        assert [row[0] for row in result["identities"]]==removable,result
        for name,rows in result["identities"]:
            expected=[]
            for path in [root/name,*sorted((root/name).rglob("*"))]:
                m=os.lstat(path)
                expected.append(["." if path==root/name else str(path.relative_to(root/name)),m.st_dev,
                    m.st_ino,m.st_mode,m.st_size,m.st_mtime_ns,m.st_ctime_ns])
            assert rows==expected,rows
    for payload in ({**options,"extra":1},{**options,"int_digits":options["int_digits"]+1}):
        done=subprocess.run([str(native),str(entry),"--registry-read-probe","retention-plan"],
            input=json.dumps(payload).encode(),env={**env,"MORU_HOOK_SOFT_FAIL":"1"},cwd=project,
            capture_output=True,timeout=8)
        assert (done.returncode,done.stdout,done.stderr)==(125,b"",b""),done
    assert before==snapshot()
    return 5
