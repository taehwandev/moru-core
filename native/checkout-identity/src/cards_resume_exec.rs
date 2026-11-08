//! owner: CardResumeExec; allowed imports: libc/std; forbidden imports: shell fallback,
//! executable inspection, provider retries or post-fork allocation/locks;
//! callers/tests: resume child; PATH/errno/FD process parity and byte-path unit tests.
//! Reference: CPython v3.9.6 Modules/_posixsubprocess.c child_exec search loop.
use std::{
    ffi::{CString, OsStr},
    fs, io,
    os::unix::{ffi::OsStrExt, process::CommandExt},
    path::Path,
    process::{Child, Command},
    ptr,
};

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn _NSGetEnviron() -> *mut *mut *mut libc::c_char;
}
#[cfg(target_os = "linux")]
unsafe extern "C" {
    static mut environ: *mut *mut libc::c_char;
}

pub(crate) struct CardResumeExec;

impl CardResumeExec {
    pub(crate) fn spawn(project: &Path, session: &str) -> io::Result<Child> {
        let path =
            std::env::var_os("PATH").unwrap_or_else(|| env!("MORU_PYTHON_DEFAULT_PATH").into());
        let candidates = Self::candidates(&path)?;
        let program = CString::new("codex").unwrap();
        let action = CString::new("resume").unwrap();
        let session =
            CString::new(session).map_err(|_| io::Error::from_raw_os_error(libc::EINVAL))?;
        // The input reader is joined before this call. Snapshot while the parent
        // descriptor table is quiescent; Rust creates its error pipe afterwards.
        let descriptors = Self::descriptors()?;
        let mut command = Command::new("codex");
        command
            .arg("resume")
            .arg(OsStr::from_bytes(session.as_bytes()))
            .current_dir(project);
        unsafe {
            command.pre_exec(move || {
                // std already applies cwd/stdin/out before this closure. Restore
                // Python's ignored signals, keeping the inherited signal mask.
                let mut reset: libc::sigaction = std::mem::zeroed();
                reset.sa_sigaction = libc::SIG_DFL;
                libc::sigemptyset(&mut reset.sa_mask);
                for signal in [libc::SIGPIPE, libc::SIGXFSZ] {
                    if libc::sigaction(signal, &reset, ptr::null_mut()) != 0 {
                        return Err(io::Error::from_raw_os_error(Self::errno()));
                    }
                }
                for &fd in &descriptors {
                    libc::close(fd);
                }
                let argv = [
                    program.as_ptr(),
                    action.as_ptr(),
                    session.as_ptr(),
                    ptr::null(),
                ];
                let environment = Self::environment();
                let mut first = 0;
                let mut last = libc::ENOENT;
                for candidate in &candidates {
                    libc::execve(candidate.as_ptr(), argv.as_ptr(), environment);
                    last = Self::errno();
                    if first == 0 && last != libc::ENOENT && last != libc::ENOTDIR {
                        first = last;
                    }
                }
                // Always fail on return: std's execvp (including implicit shell
                // handling of ENOEXEC) must never run after this search.
                Err(io::Error::from_raw_os_error(if first != 0 {
                    first
                } else {
                    last
                }))
            });
        }
        command.spawn()
    }

    fn candidates(path: &OsStr) -> io::Result<Vec<CString>> {
        path.as_bytes()
            .split(|byte| *byte == b':')
            .map(|directory| {
                let mut candidate = directory.to_vec();
                if !candidate.is_empty() && !candidate.ends_with(b"/") {
                    candidate.push(b'/');
                }
                candidate.extend_from_slice(b"codex");
                CString::new(candidate).map_err(|_| io::Error::from_raw_os_error(libc::EINVAL))
            })
            .collect()
    }

    fn descriptors() -> io::Result<Vec<libc::c_int>> {
        #[cfg(target_os = "macos")]
        let directory = "/dev/fd";
        #[cfg(target_os = "linux")]
        let directory = "/proc/self/fd";
        Self::descriptors_from(Path::new(directory))
    }

    fn descriptors_from(directory: &Path) -> io::Result<Vec<libc::c_int>> {
        // Drop ReadDir/DirEntry before filtering out their closed own FD.
        // CPython falls back to brute-force close when FD enumeration is absent
        // or fails. Filter in the parent so later-created error pipes stay open.
        match Self::directory_descriptors(directory) {
            Ok(inventory) => Self::live_descriptors(inventory),
            Err(_) => {
                let maximum = Self::scan_limit(unsafe { libc::sysconf(libc::_SC_OPEN_MAX) });
                Self::live_descriptors((3..maximum).map(|fd| fd as libc::c_int))
            }
        }
    }

    fn directory_descriptors(directory: &Path) -> io::Result<Vec<libc::c_int>> {
        let mut inventory = Vec::new();
        for entry in fs::read_dir(directory)? {
            let name = entry?.file_name();
            if let Some(fd) = name
                .to_str()
                .and_then(|name| name.parse::<libc::c_int>().ok())
                .filter(|fd| *fd >= 3)
            {
                inventory
                    .try_reserve(1)
                    .map_err(|_| io::Error::from_raw_os_error(libc::ENOMEM))?;
                inventory.push(fd);
            }
        }
        Ok(inventory)
    }

    fn scan_limit(probed: libc::c_long) -> libc::c_long {
        let maximum = if probed == -1 { 256 } else { probed };
        // FDs are c_int. Include every representable number without allowing
        // the C reference's int-loop overflow for a larger reported bound.
        maximum.min(libc::c_int::MAX as libc::c_long + 1)
    }

    fn live_descriptors(
        inventory: impl IntoIterator<Item = libc::c_int>,
    ) -> io::Result<Vec<libc::c_int>> {
        let mut descriptors = Vec::new();
        for fd in inventory {
            loop {
                if unsafe { libc::fcntl(fd, libc::F_GETFD) } >= 0 {
                    descriptors
                        .try_reserve(1)
                        .map_err(|_| io::Error::from_raw_os_error(libc::ENOMEM))?;
                    descriptors.push(fd);
                    break;
                }
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                if error.raw_os_error() != Some(libc::EBADF) {
                    return Err(error);
                }
                break;
            }
        }
        descriptors.sort_unstable();
        descriptors.dedup();
        Ok(descriptors)
    }

    fn environment() -> *const *const libc::c_char {
        #[cfg(target_os = "macos")]
        unsafe {
            *_NSGetEnviron() as *const *const libc::c_char
        }
        #[cfg(target_os = "linux")]
        unsafe {
            environ as *const *const libc::c_char
        }
    }

    fn errno() -> libc::c_int {
        #[cfg(target_os = "macos")]
        unsafe {
            *libc::__error()
        }
        #[cfg(target_os = "linux")]
        unsafe {
            *libc::__errno_location()
        }
    }
}

#[cfg(test)]
#[path = "cards_resume_exec_tests.rs"]
mod tests;
