//! owner: ResumeSignalMask; allowed imports: libc/std; forbidden imports: IO/state;
//! callers/tests: resume reader-thread signal inheritance; verification: scoped mask tests.
use std::{io, marker::PhantomData, mem, ptr, rc::Rc};

pub(crate) struct ResumeSignalMask {
    previous: libc::sigset_t,
    // Signal masks belong to a thread; restoring on another thread is incorrect.
    _thread: PhantomData<Rc<()>>,
}

impl ResumeSignalMask {
    pub(crate) fn block_int() -> io::Result<Self> {
        Self::change_int(libc::SIG_BLOCK)
    }

    #[cfg(test)]
    pub(crate) fn unblock_int() -> io::Result<Self> {
        Self::change_int(libc::SIG_UNBLOCK)
    }

    fn change_int(how: libc::c_int) -> io::Result<Self> {
        let mut blocked: libc::sigset_t = unsafe { mem::zeroed() };
        let mut previous: libc::sigset_t = unsafe { mem::zeroed() };
        if unsafe { libc::sigemptyset(&mut blocked) } != 0
            || unsafe { libc::sigaddset(&mut blocked, libc::SIGINT) } != 0
        {
            return Err(io::Error::last_os_error());
        }
        let error = unsafe { libc::pthread_sigmask(how, &blocked, &mut previous) };
        if error != 0 {
            return Err(io::Error::from_raw_os_error(error));
        }
        Ok(Self {
            previous,
            _thread: PhantomData,
        })
    }
}

impl Drop for ResumeSignalMask {
    fn drop(&mut self) {
        // This mask came from the same thread's successful pthread_sigmask call.
        unsafe {
            libc::pthread_sigmask(libc::SIG_SETMASK, &self.previous, ptr::null_mut());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards_resume_signal::{ResumeInterrupt, TEST_LOCK};

    fn current() -> libc::sigset_t {
        let mut mask = unsafe { mem::zeroed() };
        assert_eq!(
            unsafe { libc::pthread_sigmask(libc::SIG_SETMASK, ptr::null(), &mut mask) },
            0
        );
        mask
    }
    fn member(mask: &libc::sigset_t, signal: i32) -> i32 {
        unsafe { libc::sigismember(mask, signal) }
    }

    #[test]
    fn mask_is_inherited_by_new_threads_and_restores_all_prior_bits() {
        let _lock = TEST_LOCK.lock().unwrap();
        let previous = current();
        let _restore = ResumeSignalMask {
            previous,
            _thread: PhantomData,
        };
        let mut inherited = current();
        unsafe {
            libc::sigaddset(&mut inherited, libc::SIGUSR1);
        }
        assert_eq!(
            unsafe { libc::pthread_sigmask(libc::SIG_SETMASK, &inherited, ptr::null_mut()) },
            0
        );
        let guard = ResumeInterrupt::block_current().unwrap();
        assert_eq!(member(&current(), libc::SIGINT), 1);
        let child = std::thread::spawn(|| {
            let mask = current();
            (member(&mask, libc::SIGINT), member(&mask, libc::SIGUSR1))
        })
        .join()
        .unwrap();
        assert_eq!(child, (1, 1));
        drop(guard);
        let restored = current();
        for signal in [libc::SIGINT, libc::SIGUSR1, libc::SIGTERM, libc::SIGHUP] {
            assert_eq!(member(&restored, signal), member(&inherited, signal));
        }
    }

    #[test]
    fn an_inherited_blocked_sigint_stays_blocked_after_nested_guard_drop() {
        let _lock = TEST_LOCK.lock().unwrap();
        let previous = current();
        let inherited = ResumeInterrupt::block_current().unwrap();
        let nested = ResumeInterrupt::block_current().unwrap();
        drop(nested);
        assert_eq!(member(&current(), libc::SIGINT), 1);
        drop(inherited);
        assert_eq!(
            member(&current(), libc::SIGINT),
            member(&previous, libc::SIGINT)
        );
    }
}
