//! owner: guarded directory descriptors and atomic sibling replacement;
//! allowed imports: std and libc file primitives;
//! forbidden imports: receipt schemas, authorization and workflow state;
//! callers/tests: publication receipts and document delivery marker fixtures;
//! verification: path anchoring, modes, collision ownership and cleanup.
use std::{
    ffi::{CStr, CString},
    fs::File,
    io::{self, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::ffi::OsStrExt,
    },
    path::{Component, Path},
};

pub(crate) enum AtomicSibling {
    Private,
    InheritUmask,
}

impl AtomicSibling {
    pub(crate) fn open_directory(path: &Path) -> Option<File> {
        let mut dir = File::open("/").ok()?;
        for part in path.strip_prefix("/").ok()?.components() {
            let Component::Normal(name) = part else {
                return None;
            };
            let name = CString::new(name.as_bytes()).ok()?;
            dir = Self::open_relative(&dir, &name, libc::O_RDONLY | libc::O_DIRECTORY)?;
        }
        Some(dir)
    }

    pub(crate) fn open_relative(dir: &File, path: &CStr, flags: libc::c_int) -> Option<File> {
        Self::open_relative_result(dir, path, flags).ok()
    }

    pub(crate) fn ensure_directory(parent: &File, name: &CStr) -> Option<File> {
        let flags = libc::O_RDONLY | libc::O_DIRECTORY;
        match Self::open_relative_result(parent, name, flags) {
            Ok(dir) => return Some(dir),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return None,
        }
        // Anchor both operations at the same parent, even with concurrent creators.
        unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o777 as libc::mode_t) };
        Self::open_relative(parent, name, flags)
    }

    pub(crate) fn open_relative_result(
        dir: &File,
        path: &CStr,
        flags: libc::c_int,
    ) -> io::Result<File> {
        Self::open_relative_with_mode(dir, path, flags, 0o666)
    }

    pub(crate) fn open_relative_with_mode(
        dir: &File,
        path: &CStr,
        flags: libc::c_int,
        mode: libc::c_uint,
    ) -> io::Result<File> {
        let fd = unsafe {
            libc::openat(
                dir.as_raw_fd(),
                path.as_ptr(),
                flags | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC,
                mode,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { File::from_raw_fd(fd) })
    }

    pub(crate) fn try_append_lock(dir: &File, name: &CStr) -> Option<File> {
        let file = Self::open_relative(dir, name, libc::O_WRONLY | libc::O_APPEND | libc::O_CREAT)?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        (unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0)
            .then_some(file)
    }

    pub(crate) fn replace(
        self,
        dir: &File,
        temporary: &CStr,
        target: &CStr,
        bytes: &[u8],
    ) -> io::Result<()> {
        let dir = dir.as_raw_fd();
        let mode_bits = match self {
            Self::Private => 0o600,
            Self::InheritUmask => 0o666,
        };
        let fd = unsafe {
            libc::openat(
                dir,
                temporary.as_ptr(),
                libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_CLOEXEC,
                mode_bits as libc::c_uint,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        let mut file = unsafe { File::from_raw_fd(fd) };
        let result = file
            .write_all(bytes)
            .and_then(|_| file.flush())
            .and_then(|_| {
                if matches!(self, Self::Private) {
                    unsafe { libc::fchmod(fd, 0o600) };
                }
                drop(file);
                if unsafe { libc::renameat(dir, temporary.as_ptr(), dir, target.as_ptr()) } == 0 {
                    Ok(())
                } else {
                    Err(io::Error::last_os_error())
                }
            });
        if result.is_err() {
            // Only remove the temporary directory entry this operation created.
            unsafe { libc::unlinkat(dir, temporary.as_ptr(), 0) };
        }
        result
    }
}
