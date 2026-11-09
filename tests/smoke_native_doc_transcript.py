"""Source-bound transcript queries in a transported consumer without Python PATH."""
import json
import subprocess


def check_doc_transcript(native, entry, base, project, env):
    path=base/"synthetic-doc-transcript.jsonl"
    def invoke(operation,fields,value):
        before=path.read_bytes()
        done=subprocess.run([str(native),str(entry),"--doc-transcript-probe",operation],
            input=json.dumps({"path":str(path),**fields}).encode(),cwd=project,env=env,
            capture_output=True,timeout=8)
        assert (done.returncode,done.stderr)==(0,b""),done
        assert json.loads(done.stdout)=={"schema_version":1,"result":{"value":value}},done
        assert before==path.read_bytes()
    row=b'{"type":"compacted"}'
    path.write_bytes(row+b"\n")
    length=path.stat().st_size
    invoke("compacted",{},True)
    invoke("aligned",{"fallback":0},length)
    invoke("due",{"offset":0,"redeliveries":0,"limit":3},True)
    invoke("due",{"offset":length,"redeliveries":0,"limit":3},False)
    invoke("due",{"offset":0,"redeliveries":3,"limit":3},False)
    path.write_bytes(b"prefix\n"+row)
    invoke("compacted",{},True)
    invoke("aligned",{"fallback":0},7)
    invoke("due",{"offset":7,"redeliveries":0,"limit":3},False)
    path.write_bytes(b"prefix\n"+b"x"*70000)
    invoke("aligned",{"fallback":7},7)
    return 9
