"""Transported native session-picker checks with an owned shell provider."""
import json
import shutil
import sqlite3
import subprocess


def check_card_resume(entry, base, project, repo, normal):
    from contextlib import closing
    from agent_work_cards import _SCHEMA

    state=base/"resume-state"
    database=state/"work-cards/cards.sqlite3"
    database.parent.mkdir(parents=True)
    sessions=("01a0f571-0366-7863-ba96-0a9aa4ddf9fc","01a0f571-0366-7863-ba96-0a9aa4ddf9fd")
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(_SCHEMA)
        connection.execute("PRAGMA user_version=3")
        connection.executemany("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(repo,key*32,"synthetic resume 한😀","test","/removed-worktree",status,"created",stamp,
              key*32,"codex",session) for key,status,stamp,session in
             (("a","done","2026-11-01",sessions[0]),("b","active","2026-11-02",sessions[1]))])
        connection.commit()
    binary=base/"resume-bin"
    binary.mkdir()
    (binary/"git").symlink_to(shutil.which("git"))
    record=base/"resume-record"
    provider=binary/"codex"
    provider.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" >> "$MORU_TEST_RESUME_RECORD"\nexit 7\n')
    provider.chmod(0o755)
    env={**normal,"MORU_STATE_HOME":str(state),"PATH":str(binary),"MORU_TEST_RESUME_RECORD":str(record)}
    def invoke(data):
        record.unlink(missing_ok=True)
        before=database.read_bytes()
        done=subprocess.run([str(entry),"work-cards","--project",str(project),"resume"],
            input=data,capture_output=True,cwd=project,env=env,timeout=8)
        assert before==database.read_bytes()
        return done
    for data,status,selected in ((b"2\n",7,True),(b"\n",0,False),(b"0\n",2,False),(b"",0,False)):
        done=invoke(data)
        assert done.returncode==status,done
        assert b"Codex tasks (choose a number; Enter cancels):" in done.stdout,done
        if selected:
            assert record.read_text().splitlines()==[str(project),"resume",sessions[0]]
        else:
            assert not record.exists()
    legacy=base/"resume-old-project"
    evidence=legacy/".moru/runs"/("a"*32)/"preflight.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({"work":{"id":"a"*32},"runtime_session":{"runtime":"codex","session_id":sessions[0]}}))
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE cards SET runtime='',session_id='',project=? WHERE work_id=?",(str(legacy),"a"*32))
        connection.commit()
    before=evidence.read_bytes()
    assert invoke(b"2\n").returncode==7
    assert record.read_text().splitlines()==[str(project),"resume",sessions[0]]
    assert before==evidence.read_bytes()
    return 5
