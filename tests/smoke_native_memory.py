"""Transported memory ranking without Python, Git or user-store IO."""
import json
import subprocess
import unicodedata


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
    return 4
