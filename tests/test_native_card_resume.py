"""Native picker and shell-only provider preserve exact session/navigation effects."""
from contextlib import closing
import fcntl
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import sqlite3
import subprocess
import sys
import termios
import time
import unittest

import agent_work_cards as cards
import test_native_work_cards as fixtures

SESSION = "01a0f571-0366-7863-ba96-0a9aa4ddf9fc"
OTHER = "01a0f571-0366-7863-ba96-0a9aa4ddf9fd"
CHANGED = "01a0f571-0366-7863-ba96-0a9aa4ddf9fe"


class NativeCardResumeTests(unittest.TestCase):
    key = fixtures.NativeWorkCardTests.key
    store = fixtures.NativeWorkCardTests.store
    insert = fixtures.NativeWorkCardTests.insert

    def setUp(self):
        fixtures.NativeWorkCardTests.setUp(self)
        self.record = self.base/"provider-record"
        self.bin = self.base/"resume-bin"
        self.bin.mkdir()
        (self.bin/"git").symlink_to(shutil.which("git"))
        self.python_bin = self.base/"reference-python"
        self.python_bin.mkdir()
        (self.python_bin/"python3").symlink_to(sys.executable)
        self.codex = self.bin/"codex"
        self.codex.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" >> "$MORU_TEST_RESUME_RECORD"\n'
            'if [ -n "${MORU_TEST_RESUME_FD:-}" ]; then\n'
            ' if [ -e "/dev/fd/$MORU_TEST_RESUME_FD" ]; then state=open; else state=closed; fi\n'
            ' printf "fd:%s\\n" "$state" >> "$MORU_TEST_RESUME_RECORD"\nfi\n'
            'if [ "${MORU_TEST_RESUME_READ:-}" = 1 ]; then\n IFS= read -r rest || :\n'
            ' printf "stdin:%s\\n" "$rest" >> "$MORU_TEST_RESUME_RECORD"\nfi\n'
            'if [ "${MORU_TEST_RESUME_WAIT:-}" = 1 ]; then\n trap "" INT\n'
            ' printf "pid:%s\\n" "$$" >> "$MORU_TEST_RESUME_RECORD"\n exec /bin/sleep 30\nfi\n'
            'if [ "${MORU_TEST_RESUME_SIGNAL:-}" = TERM ]; then kill -TERM "$$"; fi\n'
            'if [ "${MORU_TEST_RESUME_SIGNAL:-}" = PIPE ]; then kill -PIPE "$$"; fi\n'
            'if [ "${MORU_TEST_RESUME_SIGNAL:-}" = XFSZ ]; then kill -XFSZ "$$"; fi\n'
            'exit "${MORU_TEST_RESUME_EXIT:-0}"\n')
        self.codex.chmod(0o755)

    def seed(self, count=2, version=3, direct=True):
        if self.database.exists(): self.database.unlink()
        with closing(self.store(version,wal=True)) as connection:
            for index in range(1,count+1):
                self.insert(connection,index,state="done" if index==1 else "active",
                    stamp=f"2026-11-{index:02}T00:00:00+00:00")
                connection.execute("UPDATE cards SET summary=? WHERE work_id=?",
                    (f"선택😀 {index}",f"{index:032x}"))
                if direct:
                    connection.execute("UPDATE cards SET runtime='codex',session_id=? WHERE work_id=?",
                        (SESSION if index==1 else OTHER,f"{index:032x}"))
            connection.commit()

    def environment(self,native=True,**overrides):
        path=str(self.bin) if native else str(self.bin)+os.pathsep+str(self.python_bin)
        return {**self.env,"PATH":path,"MORU_LAUNCHER_BACKEND":"auto" if native else "python",
            "MORU_TEST_RESUME_RECORD":str(self.record),**overrides}

    def command(self,args=None):
        return [str(self.entry),"work-cards",*(args or ["--project",str(self.project),"resume"])]

    def call(self,data=b"1\n",native=True,args=None,**env):
        self.record.unlink(missing_ok=True)
        done=subprocess.run(self.command(args),input=data,env=self.environment(native,**env),
            cwd=self.project,capture_output=True,timeout=8)
        effect=self.record.read_bytes() if self.record.exists() else None
        return (done.returncode,done.stdout,done.stderr),effect

    def parity(self,data=b"1\n",args=None,**env):
        expected=self.call(data,False,args,**env)
        self.assertEqual(expected,self.call(data,True,args,**env))
        return expected

    def test_explicit_selection_uses_exact_frozen_order_and_returns_provider_status(self):
        self.seed()
        before=self.database.read_bytes()
        result,effect=self.parity(b"2\n",MORU_TEST_RESUME_EXIT="7")
        self.assertEqual(7,result[0])
        self.assertEqual(b"",result[2])
        self.assertIn("1. 선택😀 2 [active, 2026-11-02]".encode(),result[1])
        self.assertIn("2. 선택😀 1 [done, 2026-11-01]".encode(),result[1])
        self.assertEqual([str(self.project),"resume",SESSION],effect.decode().splitlines())
        self.assertEqual(before,self.database.read_bytes())

    def test_cancel_eof_invalid_unicode_nul_and_integer_boundaries_never_guess(self):
        self.seed(1)
        for data in (b"",b"\n",b" \t\n","\u2000\u0085\n".encode()):
            with self.subTest(data=data):
                result,effect=self.parity(data)
                self.assertEqual(0,result[0]); self.assertIsNone(effect)
        for data in (b"0\n",b"2\n",b"-1\n",b"+1\n",b"latest\n",b"1_0\n",
                     "١\n".encode(),b"1\x00\n",b"\xff\n",b"9"*5001+b"\n"):
            with self.subTest(data=data[:20]):
                result,effect=self.parity(data)
                self.assertEqual(2,result[0]); self.assertIsNone(effect)
        result,effect=self.parity(b"0"*5000+b"1\n")
        self.assertEqual(2 if getattr(sys,"get_int_max_str_digits",lambda:0)() else 0,result[0])
        self.assertEqual(None if result[0] else [str(self.project),"resume",SESSION],
            effect.decode().splitlines() if effect else None)

    def test_unicode_strip_crlf_no_newline_and_read_ahead_match_original(self):
        self.seed(1)
        for data in (b"1",b"1\r",b"1\r\n",b"1\rignored\n",
                     "\u20001\u00a0\n".encode(),b"0001\n",b"1\nremaining input\n"):
            with self.subTest(data=data):
                result,effect=self.parity(data,MORU_TEST_RESUME_READ="1")
                if data == b"1\rignored\n":
                    self.assertEqual(2,result[0]); self.assertIsNone(effect)
                    continue
                self.assertEqual(0,result[0])
                self.assertEqual("stdin:",effect.decode().splitlines()[-1])

    def test_legacy_evidence_requires_exact_work_without_latest_and_preserves_bytes(self):
        for version in (0,1,2,3):
            self.seed(1,version,direct=False)
            evidence=self.project/".moru/runs"/f"{1:032x}"/"preflight.json"
            evidence.parent.mkdir(parents=True,exist_ok=True)
            evidence.write_text(json.dumps({"work":{"id":f"{1:032x}"},
                "runtime_session":{"runtime":"codex","session_id":SESSION}}))
            before=self.database.read_bytes(),evidence.read_bytes()
            result,effect=self.parity()
            self.assertEqual(0,result[0]); self.assertIn(SESSION.encode(),effect)
            self.assertEqual(before,(self.database.read_bytes(),evidence.read_bytes()))
            evidence.write_text(json.dumps({"work":{"id":"f"*32},
                "runtime_session":{"runtime":"codex","session_id":OTHER}}))
            result,effect=self.parity()
            self.assertEqual(2,result[0]); self.assertNotIn(b"Codex tasks",result[1]); self.assertIsNone(effect)

    def test_invalid_explicit_binding_never_falls_back_to_legacy_or_latest(self):
        self.seed(1)
        evidence=self.project/".moru/runs"/f"{1:032x}"/"preflight.json"
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({"work":{"id":f"{1:032x}"},
            "runtime_session":{"runtime":"codex","session_id":OTHER}}))
        for runtime,session in (("codex","--last"),("claude",SESSION),("codex",SESSION.upper()),
                                ("codex",SESSION.replace("-","")),("codex","")):
            with closing(sqlite3.connect(self.database)) as connection:
                connection.execute("UPDATE cards SET runtime=?,session_id=?",(runtime,session)); connection.commit()
            result,effect=self.parity()
            self.assertEqual(2,result[0]); self.assertIsNone(effect)

    def test_missing_and_unbound_store_never_print_picker_or_create_state(self):
        result,effect=self.parity()
        self.assertEqual((2,b"",b"work cards: no tasks with a recorded Codex session in this repository\n"),result)
        self.assertIsNone(effect); self.assertFalse(self.database.parent.exists())
        self.seed(1,direct=False)
        self.assertEqual(2,self.parity()[0][0])

    def test_stored_removed_project_is_unused_for_explicit_binding_and_current_repo_is_cwd(self):
        self.seed(1)
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE cards SET project=?,run_id=?",(str(self.base/"removed-worktree"),b"\x00\xff")); connection.commit()
        result,effect=self.parity(args=["resume"])
        self.assertEqual(0,result[0])
        self.assertEqual(str(self.project),effect.decode().splitlines()[0])

    def test_provider_missing_denied_and_child_signal_match_without_fallback(self):
        self.seed(1)
        result,effect=self.parity(MORU_TEST_RESUME_SIGNAL="TERM")
        self.assertEqual(241,result[0]); self.assertIsNotNone(effect)
        self.codex.chmod(0o600)
        result,effect=self.parity()
        self.assertEqual(2,result[0]); self.assertIn(b"Permission denied: 'codex'",result[2]); self.assertIsNone(effect)
        self.codex.write_text('printf "unexpected-shell-fallback\\n" >> "$MORU_TEST_RESUME_RECORD"\n')
        self.codex.chmod(0o755)
        result,effect=self.parity()
        self.assertEqual(2,result[0]); self.assertIn(b"Exec format error: 'codex'",result[2]); self.assertIsNone(effect)
        self.codex.unlink()
        result,effect=self.parity()
        self.assertEqual(2,result[0]); self.assertIn(b"No such file or directory: 'codex'",result[2]); self.assertIsNone(effect)

    def test_existing_soft_fail_convention_applies_to_provider_status(self):
        self.seed(1)
        result,effect=self.parity(MORU_TEST_RESUME_EXIT="7",MORU_HOOK_SOFT_FAIL="1")
        self.assertEqual(0,result[0]); self.assertIn(SESSION.encode(),effect)

    def test_path_search_tries_later_candidates_and_preserves_first_meaningful_errno(self):
        self.seed(1)
        first=self.base/"first-path-candidate"; first.mkdir()
        candidate=first/"codex"
        candidate.write_text('printf "unexpected-first-shell\\n" >> "$MORU_TEST_RESUME_RECORD"\n')
        candidate.chmod(0o755)
        def compare():
            expected=self.call(native=False,PATH=str(first)+os.pathsep+self.environment(False)["PATH"])
            self.assertEqual(expected,self.call(native=True,PATH=str(first)+os.pathsep+self.environment(True)["PATH"]))
            return expected
        result,effect=compare()
        self.assertEqual(0,result[0]); self.assertNotIn(b"unexpected",effect)
        candidate.chmod(0o600)
        self.assertEqual(0,compare()[0][0])
        candidate.chmod(0o755); self.codex.chmod(0o600)
        result,effect=compare()
        self.assertEqual(2,result[0]); self.assertIn(b"Exec format error",result[2]); self.assertIsNone(effect)
        candidate.unlink()
        result,effect=compare()
        self.assertEqual(2,result[0]); self.assertIn(b"Permission denied",result[2]); self.assertIsNone(effect)

    def test_provider_does_not_inherit_extra_open_descriptors(self):
        self.seed(1)
        incoming,outgoing=os.pipe()
        inherited=fcntl.fcntl(incoming,fcntl.F_DUPFD,128)
        try:
            outcomes=[]
            for native in (False,True):
                self.record.unlink(missing_ok=True)
                done=subprocess.run(self.command(),input=b"1\n",capture_output=True,cwd=self.project,
                    env=self.environment(native,MORU_TEST_RESUME_FD=str(inherited)),
                    pass_fds=(inherited,),timeout=8)
                outcomes.append(((done.returncode,done.stdout,done.stderr),self.record.read_bytes()))
            self.assertEqual(outcomes[0],outcomes[1])
            self.assertEqual(b"fd:closed",outcomes[1][1].splitlines()[-1])
        finally:
            os.close(inherited); os.close(incoming); os.close(outgoing)

    def test_provider_restores_python_child_signal_defaults(self):
        self.seed(1)
        for name,number in (("PIPE",signal.SIGPIPE),("XFSZ",signal.SIGXFSZ)):
            outcomes=[]
            for native in (False,True):
                self.record.unlink(missing_ok=True)
                done=subprocess.run(self.command(),input=b"1\n",capture_output=True,cwd=self.project,
                    env=self.environment(native,MORU_TEST_RESUME_SIGNAL=name),timeout=8,
                    preexec_fn=lambda:signal.signal(number,signal.SIG_IGN))
                outcomes.append(((done.returncode,done.stdout,done.stderr),self.record.read_bytes()))
            self.assertEqual(outcomes[0],outcomes[1],name)
            self.assertEqual(256-number,outcomes[1][0][0])

    def test_inherited_sigchld_ignore_preserves_auto_reaped_provider_status(self):
        self.seed(1)
        outcomes=[]
        for native in (False,True):
            self.record.unlink(missing_ok=True)
            done=subprocess.run(self.command(),input=b"1\n",capture_output=True,cwd=self.project,
                env=self.environment(native,MORU_TEST_RESUME_EXIT="7"),timeout=5,
                preexec_fn=lambda:signal.signal(signal.SIGCHLD,signal.SIG_IGN))
            outcomes.append(((done.returncode,done.stdout,done.stderr),self.record.read_bytes()))
        self.assertEqual(outcomes[0],outcomes[1])

    def _until_prompt(self,fd):
        output=b""
        deadline=time.monotonic()+8
        while not output.endswith(b"> "):
            self.assertLess(time.monotonic(),deadline,output)
            readable,_,_=select.select([fd],[],[],max(0,deadline-time.monotonic()))
            self.assertTrue(readable,output)
            chunk=os.read(fd,8192)
            self.assertTrue(chunk,output)
            output+=chunk
        return output

    def test_selection_uses_displayed_snapshot_after_board_changes(self):
        for native in (False,True):
            self.seed(1)
            self.record.unlink(missing_ok=True)
            process=subprocess.Popen(self.command(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,env=self.environment(native),cwd=self.project)
            try:
                prefix=self._until_prompt(process.stdout.fileno())
                with closing(sqlite3.connect(self.database)) as connection:
                    connection.execute("UPDATE cards SET session_id=?",(CHANGED,)); connection.commit()
                stdout,stderr=process.communicate(b"1\n",timeout=5)
                self.assertEqual((0,b"",b""),(process.returncode,stdout,stderr),prefix)
                self.assertEqual([str(self.project),"resume",SESSION],self.record.read_text().splitlines())
            finally:
                if process.poll() is None: process.kill(); process.communicate()

    def test_ctrl_c_during_prompt_cancels_without_provider_launch(self):
        self.seed(1)
        outputs=[]
        for native in (False,True):
            self.record.unlink(missing_ok=True)
            master,slave=pty.openpty()
            process=subprocess.Popen(self.command(),stdin=slave,stdout=slave,stderr=slave,
                env=self.environment(native),cwd=self.project,start_new_session=True)
            os.close(slave)
            try:
                output=self._until_prompt(master)
                os.kill(process.pid,signal.SIGINT)
                self.assertEqual(0,process.wait(timeout=5))
                self.assertFalse(self.record.exists())
                outputs.append(output)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                os.close(master)
        self.assertEqual(outputs[0],outputs[1])

    def test_inherited_ignored_interrupt_remains_ignored_until_explicit_cancel(self):
        self.seed(1)
        for native in (False,True):
            self.record.unlink(missing_ok=True)
            process=subprocess.Popen(self.command(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,env=self.environment(native),cwd=self.project,
                preexec_fn=lambda:signal.signal(signal.SIGINT,signal.SIG_IGN))
            try:
                self._until_prompt(process.stdout.fileno())
                os.kill(process.pid,signal.SIGINT)
                stdout,stderr=process.communicate(b"\n",timeout=5)
                self.assertEqual((0,b"",b""),(process.returncode,stdout,stderr))
                self.assertFalse(self.record.exists())
            finally:
                if process.poll() is None: process.kill(); process.communicate()

    def test_tty_stderr_prompt_nul_stdio_and_read_ahead_match_original(self):
        self.seed(1)
        for data in (b"1\n",b"\x04",b"1\x00junk\n\n",b"1\xff\n",b"1\nremaining input\n"):
            with self.subTest(data=data):
                expected=self._terminal(data,False)
                self.assertEqual(expected,self._terminal(data,True),data)
                self.assertEqual(b"> ",expected[2][:2])
                self.assertNotIn(b"> ",expected[1])

    def test_tty_partial_eof_profile_preserves_unconditional_last_byte_drop(self):
        self.seed(1)
        for data,status,selected in ((b"1",0,False),(b"12",0,True),(b"123",2,False)):
            expected=self._terminal(data,False,partial_eof=True)
            self.assertEqual(expected,self._terminal(data,True,partial_eof=True),data)
            self.assertEqual(status,expected[0]); self.assertEqual(selected,expected[3] is not None)

    def _terminal(self,data,native,partial_eof=False):
        self.record.unlink(missing_ok=True)
        master,slave=pty.openpty()
        attrs=termios.tcgetattr(slave); attrs[3]&=~termios.ECHO
        if partial_eof:
            # A real TTY with finite preloaded input and immediate empty reads
            # provides deterministic partial EOF. Consecutive canonical VEOFs
            # can coalesce even when FIONREAD is already zero.
            attrs[3]&=~termios.ICANON
            attrs[6][termios.VMIN]=0; attrs[6][termios.VTIME]=0
        termios.tcsetattr(slave,termios.TCSANOW,attrs)
        if partial_eof: os.write(master,data)
        process=subprocess.Popen(self.command(),stdin=slave,stdout=slave,stderr=subprocess.PIPE,
            env=self.environment(native,MORU_TEST_RESUME_READ="1" if b"remaining input" in data else "0"),
            cwd=self.project,start_new_session=True)
        try:
            prompt=self._until_prompt(process.stderr.fileno())
            if not partial_eof: os.write(master,data)
            os.close(slave); slave=None
            process.wait(timeout=8)
            output=b""
            while True:
                try: chunk=os.read(master,8192)
                except OSError as error:
                    if error.errno != 5: raise
                    break
                if not chunk: break
                output+=chunk
            return process.returncode,output,prompt+process.stderr.read(),self.record.read_bytes() if self.record.exists() else None
        finally:
            if process.poll() is None: process.kill(); process.wait()
            if slave is not None: os.close(slave)
            process.stderr.close(); os.close(master)

    def test_tty_closed_stderr_does_not_replace_explicit_dispatch_with_prompt_error(self):
        self.seed(1)
        outcomes=[]
        for native in (False,True):
            self.record.unlink(missing_ok=True)
            master,slave=pty.openpty()
            incoming,outgoing=os.pipe(); os.close(incoming)
            process=subprocess.Popen(self.command(),stdin=slave,stdout=slave,stderr=outgoing,
                env=self.environment(native),cwd=self.project,start_new_session=True)
            os.close(slave); os.close(outgoing)
            try:
                os.write(master,b"1\n")
                self.assertEqual(0,process.wait(timeout=8))
                outcomes.append(self.record.read_bytes())
            finally:
                if process.poll() is None: process.kill(); process.wait()
                os.close(master)
        self.assertEqual(outcomes[0],outcomes[1])

    def test_nonblocking_stdin_empty_and_partial_line_match_original(self):
        self.seed(1)
        for data in (b"",b"1",b"1\r",b"invalid"):
            outcomes=[]
            for native in (False,True):
                self.record.unlink(missing_ok=True)
                incoming,outgoing=os.pipe()
                fcntl.fcntl(incoming,fcntl.F_SETFL,fcntl.fcntl(incoming,fcntl.F_GETFL)|os.O_NONBLOCK)
                if data: os.write(outgoing,data)
                try:
                    done=subprocess.run(self.command(),stdin=incoming,capture_output=True,
                        env=self.environment(native),cwd=self.project,timeout=5)
                finally:
                    os.close(incoming); os.close(outgoing)
                outcomes.append(((done.returncode,done.stdout,done.stderr),
                    self.record.read_bytes() if self.record.exists() else None))
            self.assertEqual(outcomes[0],outcomes[1],data)

    def test_provider_phase_interrupt_reaps_owned_child_and_is_never_softened(self):
        self.seed(1)
        for native in (False,True):
            for soft in ("0","1"):
                self.record.unlink(missing_ok=True)
                process=subprocess.Popen(self.command(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,cwd=self.project,env=self.environment(native,
                        MORU_TEST_RESUME_WAIT="1",MORU_HOOK_SOFT_FAIL=soft))
                child=None
                try:
                    self._until_prompt(process.stdout.fileno())
                    process.stdin.write(b"1\n"); process.stdin.flush()
                    deadline=time.monotonic()+8
                    while child is None:
                        self.assertLess(time.monotonic(),deadline)
                        lines=self.record.read_text().splitlines() if self.record.exists() else []
                        child=next((int(line[4:]) for line in lines if line.startswith("pid:")),None)
                        if child is None: time.sleep(0.01)
                    os.kill(process.pid,signal.SIGINT)
                    stdout,stderr=process.communicate(timeout=5)
                    self.assertEqual(-signal.SIGINT,process.returncode,(native,soft,stderr))
                    self.assertTrue(stderr.endswith(b"KeyboardInterrupt\n"),stderr)
                    self.assertEqual(b"",stdout)
                    with self.assertRaises(ProcessLookupError): os.kill(child,0)
                finally:
                    if process.poll() is None: process.kill(); process.communicate()
                    if child is not None:
                        try: os.kill(child,signal.SIGKILL)
                        except ProcessLookupError: pass

    def test_closed_stdout_preserves_explicit_dispatch_and_final_flush_status(self):
        self.seed(1)
        for data in (b"",b"\n",b"1\n",b"invalid\n"):
            for soft in ("0","1"):
                expected=self._closed_stdout(data,False,soft)
                self.assertEqual(expected,self._closed_stdout(data,True,soft),(data,soft))
                self.assertEqual(120,expected[0])
                self.assertEqual(data==b"1\n",expected[2] is not None)

    def _closed_stdout(self,data,native,soft="0"):
        self.record.unlink(missing_ok=True)
        incoming,outgoing=os.pipe(); os.close(incoming)
        try:
            done=subprocess.run(self.command(),input=data,stdout=outgoing,stderr=subprocess.PIPE,
                env=self.environment(native,MORU_HOOK_SOFT_FAIL=soft),cwd=self.project,timeout=8)
        finally: os.close(outgoing)
        return done.returncode,done.stderr,self.record.read_bytes() if self.record.exists() else None

    def test_long_menu_buffer_boundaries_preserve_output_and_failure_effects(self):
        self.seed(2)
        # Include both TextIOWrapper's 8KiB chunk and the host pipe's actual
        # binary-buffer boundary, using real output failure rather than a mock.
        incoming,outgoing=os.pipe()
        capacity=max(os.fstat(outgoing).st_blksize,io.DEFAULT_BUFFER_SIZE)
        os.close(incoming); os.close(outgoing)
        for count in (8000,8192,capacity-64,capacity+64,capacity*2):
            with closing(sqlite3.connect(self.database)) as connection:
                connection.execute("UPDATE cards SET summary=?",("x"*count,)); connection.commit()
            self.parity(b"2\n")
            expected=self._closed_stdout(b"2\n",False)
            self.assertEqual(expected,self._closed_stdout(b"2\n",True),count)

    def test_source_or_environment_decline_precedes_prompt_and_stdin_consumption(self):
        self.seed(1)
        spy=self.bin/"python3"
        spy.write_text('#!/bin/sh\nIFS= read -r first || :\nprintf "fallback:%s\\n" "$first"\nexit 23\n')
        spy.chmod(0o755)
        result,effect=self.call(b"original-input\n",PYTHONVERBOSE="1")
        self.assertEqual((23,b"fallback:original-input\n",b""),result)
        self.assertIsNone(effect)


if __name__ == "__main__":
    unittest.main()
