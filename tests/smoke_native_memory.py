"""Transported memory ranking without Python, Git or user-store IO."""
import json
import hashlib
import subprocess
import unicodedata
import shutil


def check_memory(native,entry,project,env):
    records=[{"id":"a","status":"active","scope":"all","review_on":"2099-01-01",
        "body":"프로필 화면 크래시; src/ui/ProfileScreen.kt","source":"checked"},
        {"id":"b","status":"active","scope":"task","review_on":"2099-01-01",
        "body":"other billing guidance","source":"checked"}]
    for context,indices in (("프로필에서는 왜 죽나",[0]),("ProfileScreen",[0]),("unrelated",[]),("",[1,0])):
        payload={"unicode":unicodedata.unidata_version,"scope":"task","today":"2026-11-09",
                 "context":context,"records":records}
        done=subprocess.run([str(native),str(entry),"--memory-probe","recall"],
            input=json.dumps(payload).encode(),capture_output=True,cwd=project,env=env,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"indices":indices}},done
    rows=[{"id":"a","replaces":None,"replaced_by":None},
          {"id":"b","replaces":"a","replaced_by":None},
          {"id":"c","replaces":"b","replaced_by":None}]
    for record_id,indices in (("a",[2,1,0]),("b",[2,1,0]),("c",[2,1,0])):
        payload={"unicode":unicodedata.unidata_version,"record_id":record_id,"records":rows}
        done=subprocess.run([str(native),str(entry),"--memory-probe","history"],
            input=json.dumps(payload).encode(),capture_output=True,cwd=project,env=env,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"indices":indices}},done
    rows[0]["replaced_by"]="missing"
    done=subprocess.run([str(native),str(entry),"--memory-probe","history"],input=json.dumps({
        "unicode":unicodedata.unidata_version,"record_id":"a","records":rows}).encode(),
        capture_output=True,cwd=project,env=env,timeout=8)
    assert (done.returncode,done.stderr)==(0,b""),done
    assert json.loads(done.stdout)=={"schema_version":1,"result":{"indices":[0]}},done
    return 8


def check_memory_files(native,entry,base,project,env):
    directory=base/"synthetic-memory-store"; directory.mkdir()
    record={"schema_version":1,"id":"a"*16,"status":"active","scope":"task",
            "body":"프로필 확인; src/ui/ProfileScreen.kt","source":"checked source","review_on":"2099-01-01"}
    content={key:record[key] for key in ("body","source","scope","review_on")}
    record["digest"]=hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path=directory/(record["id"]+".json"); path.write_text(json.dumps(record),encoding="utf-8")
    (directory/"invalid.json").write_text("invalid",encoding="utf-8")
    def invoke(operation,target,expected):
        before=path.read_bytes()
        payload={"unicode":unicodedata.unidata_version,"path":str(target)}
        done=subprocess.run([str(native),str(entry),"--memory-probe",operation],input=json.dumps(payload).encode(),
            capture_output=True,cwd=project,env=env,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":expected},done
        assert before==path.read_bytes()
    invoke("record",path,{"record":record})
    invoke("scan",directory,{"records":[record],"unreadable":1})
    path.write_text(json.dumps({**record,"body":"tampered"}),encoding="utf-8")
    invoke("record",path,{"record":None})
    invoke("scan",base/"missing-memory-store",{"records":[],"unreadable":0})
    return 4


def check_memory_source(native,entry,base,project,env):
    tools=base/"memory-source-git-only"; tools.mkdir()
    (tools/"git").symlink_to(shutil.which("git"))
    source=project/"memory-source.py"; source.write_bytes(b"raw\r\n")
    expected=hashlib.sha1(b"blob 5\0raw\r\n").hexdigest()
    def invoke(tracked,blob,path="memory-source.py",path_env=tools):
        payload={"unicode":unicodedata.unidata_version,"root":str(project),"path":path,"tracked":tracked,
                 "stdin_eof":True,"encoding":"utf-8"}
        done=subprocess.run([str(native),str(entry),"--memory-probe","blob"],input=json.dumps(payload).encode(),
            capture_output=True,cwd=project,env={**env,"PATH":str(path_env)},timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"blob":blob}},done
    invoke(False,expected)
    invoke(True,"")
    subprocess.run([str(tools/"git"),"-C",str(project),"add","--","memory-source.py"],
                   env=env,check=True,capture_output=True,timeout=5)
    before=(project/".git/index").read_bytes()
    invoke(True,expected)
    invoke(False,"",path="../outside.py")
    invoke(False,"",path_env=base/"missing-git-path")
    assert source.read_bytes()==b"raw\r\n" and (project/".git/index").read_bytes()==before
    files=[{"path":"memory-source.py","blob":expected},{"path":"missing-source.py","blob":"a"*40}]
    def status(files,blobs,expected_result,path_env=tools):
        payload={"unicode":unicodedata.unidata_version,"root":str(project),"files":files,"blobs":blobs,
                 "stdin_eof":True,"encoding":"utf-8"}
        done=subprocess.run([str(native),str(entry),"--memory-probe","source-status"],
            input=json.dumps(payload).encode(),capture_output=True,cwd=project,
            env={**env,"PATH":str(path_env)},timeout=10)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":expected_result},done
    status(files,{}, {"blobs":{"memory-source.py":expected,"missing-source.py":""},"result":{
        "source_status":"unavailable","unverified_sources":["missing-source.py"],
        "warning":"Source evidence unavailable — verify before use"}})
    status(files,{"memory-source.py":"b"*40,"missing-source.py":""},{"blobs":{},"result":{
        "source_status":"changed","unverified_sources":["memory-source.py","missing-source.py"],
        "warning":"Source evidence changed — verify before use"}},base/"missing-git-path")
    status(files[:1],{"memory-source.py":expected},{"blobs":{},"result":{"source_status":"unchanged"}},
           base/"missing-git-path")
    assert source.read_bytes()==b"raw\r\n" and (project/".git/index").read_bytes()==before
    return 8
