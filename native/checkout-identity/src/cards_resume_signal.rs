//! owner: ResumeInterrupt; allowed imports: libc/std atomics; forbidden imports:
//! IO, providers, state/files; callers/tests: picker/provider scopes and PTY tests.
pub(crate) use crate::cards_resume_signal_mask::ResumeSignalMask;
use std::{
    io, mem, ptr,
    sync::atomic::{AtomicBool, Ordering},
};

#[cfg(test)]
pub(crate) static TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

static INTERRUPTED: AtomicBool = AtomicBool::new(false);
pub(crate) struct ResumeInterrupt(Option<libc::sigaction>);

impl ResumeInterrupt {
    pub(crate) fn install() -> io::Result<Self> {
        INTERRUPTED.store(false, Ordering::SeqCst);
        let mut previous: libc::sigaction = unsafe { mem::zeroed() };
        if unsafe { libc::sigaction(libc::SIGINT, ptr::null(), &mut previous) } != 0 {
            return Err(io::Error::last_os_error());
        }
        if previous.sa_sigaction == libc::SIG_IGN {
            return Ok(Self(None));
        }
        let mut action: libc::sigaction = unsafe { mem::zeroed() };
        action.sa_sigaction = interrupt as *const () as usize;
        unsafe {
            libc::sigemptyset(&mut action.sa_mask);
        }
        if unsafe { libc::sigaction(libc::SIGINT, &action, ptr::null_mut()) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self(Some(previous)))
    }

    pub(crate) fn interrupted() -> bool {
        INTERRUPTED.load(Ordering::SeqCst)
    }

    pub(crate) fn block_current() -> io::Result<ResumeSignalMask> {
        ResumeSignalMask::block_int()
    }

    #[cfg(test)]
    pub(crate) fn test_scope() -> io::Result<(Self, ResumeSignalMask)> {
        // Race tests need a deliverable signal even when their runner inherited
        // SIG_IGN or a blocked SIGINT; restore both after this test-only scope.
        let mut previous: libc::sigaction = unsafe { mem::zeroed() };
        if unsafe { libc::sigaction(libc::SIGINT, ptr::null(), &mut previous) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let mut action: libc::sigaction = unsafe { mem::zeroed() };
        action.sa_sigaction = interrupt as *const () as usize;
        unsafe {
            libc::sigemptyset(&mut action.sa_mask);
        }
        if unsafe { libc::sigaction(libc::SIGINT, &action, ptr::null_mut()) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let scope = Self(Some(previous));
        let mask = ResumeSignalMask::unblock_int()?;
        INTERRUPTED.store(false, Ordering::SeqCst);
        Ok((scope, mask))
    }
}
impl Drop for ResumeInterrupt {
    fn drop(&mut self) {
        if let Some(previous) = &self.0 {
            unsafe {
                libc::sigaction(libc::SIGINT, previous, ptr::null_mut());
            }
        }
    }
}
extern "C" fn interrupt(_: libc::c_int) {
    INTERRUPTED.store(true, Ordering::SeqCst);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inherited_ignored_sigint_is_preserved_without_setting_the_flag() {
        let _lock = TEST_LOCK.lock().unwrap();
        let _mask = ResumeSignalMask::unblock_int().unwrap();
        let mut previous: libc::sigaction = unsafe { mem::zeroed() };
        assert_eq!(
            unsafe { libc::sigaction(libc::SIGINT, ptr::null(), &mut previous) },
            0
        );
        let _restore = ResumeInterrupt(Some(previous));
        let mut ignored = previous;
        ignored.sa_sigaction = libc::SIG_IGN;
        assert_eq!(
            unsafe { libc::sigaction(libc::SIGINT, &ignored, ptr::null_mut()) },
            0
        );
        let scope = ResumeInterrupt::install().unwrap();
        assert!(scope.0.is_none());
        assert_eq!(unsafe { libc::raise(libc::SIGINT) }, 0);
        assert!(!ResumeInterrupt::interrupted());
        drop(scope);
        let mut after: libc::sigaction = unsafe { mem::zeroed() };
        assert_eq!(
            unsafe { libc::sigaction(libc::SIGINT, ptr::null(), &mut after) },
            0
        );
        assert_eq!(after.sa_sigaction, libc::SIG_IGN);
    }
}
