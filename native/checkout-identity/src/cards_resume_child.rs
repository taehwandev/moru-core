//! owner: CardResumeChild; allowed imports: std/libc scoped interrupt; forbidden:
//! shell interpolation, extra provider calls, group kills, caches/state writes;
//! callers/tests: resume process; owned fake-provider interruption/reaping tests.
use crate::{cards_resume_exec::CardResumeExec, cards_resume_signal::ResumeInterrupt};
use std::{
    io,
    os::unix::process::ExitStatusExt,
    path::Path,
    process::{Child, ExitStatus},
    thread,
    time::{Duration, Instant},
};

pub(crate) struct CardResumeChild;

impl CardResumeChild {
    pub(crate) fn run(project: &Path, session: &str) -> io::Result<Option<i32>> {
        // Caught signals reset at exec; inherited SIG_IGN remains ignored.
        let _interrupt = ResumeInterrupt::install()?;
        let mut child = CardResumeExec::spawn(project, session)?;
        Self::wait(&mut child)
    }

    fn wait(child: &mut Child) -> io::Result<Option<i32>> {
        loop {
            if ResumeInterrupt::interrupted() {
                Self::cancel(child);
                return Ok(None);
            }
            #[cfg(test)]
            if TEST_INTERRUPT.swap(false, std::sync::atomic::Ordering::SeqCst) {
                unsafe {
                    libc::raise(libc::SIGINT);
                }
            }
            let mut raw = 0;
            // Never block after a flag load: a signal arriving just before
            // waitpid would otherwise leave no future signal to interrupt it.
            let result =
                unsafe { libc::waitpid(child.id() as libc::pid_t, &mut raw, libc::WNOHANG) };
            if result > 0 {
                let status = ExitStatus::from_raw(raw);
                if ResumeInterrupt::interrupted() {
                    return Ok(None);
                }
                return Ok(Some(
                    status
                        .code()
                        .unwrap_or_else(|| -status.signal().unwrap_or(1)),
                ));
            }
            if result == 0 {
                thread::sleep(Duration::from_millis(50));
                continue;
            }
            let error = io::Error::last_os_error();
            // Match Popen's auto-reaped/SIGCHLD-ignored convention; never send
            // a signal to a PID that the kernel no longer identifies as child.
            if error.raw_os_error() == Some(libc::ECHILD) {
                return Ok(Some(0));
            }
            if error.kind() != io::ErrorKind::Interrupted {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        }
    }

    fn cancel(child: &mut Child) {
        let deadline = Instant::now() + Duration::from_millis(250);
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Err(error) if error.raw_os_error() == Some(libc::ECHILD) => return,
                _ => {}
            }
            thread::sleep(Duration::from_millis(10));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg(test)]
static TEST_INTERRUPT: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards_resume_signal::TEST_LOCK;
    use std::{
        process::{Command, Stdio},
        sync::{atomic::Ordering, mpsc},
    };

    #[test]
    fn sigint_after_final_flag_check_cancels_without_waiting_for_child_eof() {
        let _lock = TEST_LOCK.lock().unwrap();
        let (_interrupt, _mask) = ResumeInterrupt::test_scope().unwrap();
        let mut child = Command::new("/bin/cat")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        let stdin = child.stdin.take().unwrap();
        let (done, completion) = mpsc::channel();
        // Keep the child alive until cancellation. A bounded watchdog closes
        // only this child's pipe if an unbounded wait regresses; it kills no PID.
        let watchdog = thread::spawn(move || {
            let released = completion.recv_timeout(Duration::from_secs(2)).is_err();
            drop(stdin);
            released
        });
        TEST_INTERRUPT.store(true, Ordering::SeqCst);
        let result = CardResumeChild::wait(&mut child);
        let _ = done.send(());
        assert_eq!(result.unwrap(), None);
        assert!(
            !watchdog.join().unwrap(),
            "wait blocked until the child received EOF"
        );
        assert!(
            child.try_wait().unwrap().is_some(),
            "cancel must reap its own child"
        );
    }

    #[test]
    fn owned_child_exit_signal_and_already_reaped_status_are_preserved() {
        let _lock = TEST_LOCK.lock().unwrap();
        let (_interrupt, _mask) = ResumeInterrupt::test_scope().unwrap();
        let mut child = Command::new("/bin/sh")
            .args(["-c", "exit 7"])
            .spawn()
            .unwrap();
        assert_eq!(CardResumeChild::wait(&mut child).unwrap(), Some(7));
        let mut child = Command::new("/bin/sh")
            .args(["-c", "kill -KILL $$"])
            .spawn()
            .unwrap();
        assert_eq!(
            CardResumeChild::wait(&mut child).unwrap(),
            Some(-libc::SIGKILL)
        );
        let mut child = Command::new("/bin/sh")
            .args(["-c", "exit 9"])
            .spawn()
            .unwrap();
        child.wait().unwrap();
        assert_eq!(CardResumeChild::wait(&mut child).unwrap(), Some(0));
    }
}
