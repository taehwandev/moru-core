//! Owner: enumerate immediate smoke bundle entries from anchored directory handles.
//! Allowed imports: read-only directory descriptors and POSIX enumeration.
//! Forbidden imports: writes, following directory links, recursion and providers.
//! Callers/tests: Figma frame discovery and offline smoke fixtures.
use crate::atomic_sibling::AtomicSibling;
use std::{ffi::CStr, fs::File, io, os::fd::IntoRawFd};

pub(super) fn names(root: &File, directory: &CStr) -> Option<Vec<String>> {
    let child = match AtomicSibling::open_relative_result(
        root,
        directory,
        libc::O_RDONLY | libc::O_DIRECTORY,
    ) {
        Ok(child) => child,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Some(Vec::new()),
        Err(_) => return None,
    };
    let fd = child.into_raw_fd();
    let reader = unsafe { libc::fdopendir(fd) };
    if reader.is_null() {
        unsafe { libc::close(fd) };
        return None;
    }
    let result = read_names(reader);
    unsafe { libc::closedir(reader) };
    result
}

fn read_names(reader: *mut libc::DIR) -> Option<Vec<String>> {
    let mut names = Vec::new();
    loop {
        #[cfg(target_os = "macos")]
        let errno = unsafe { libc::__error() };
        #[cfg(target_os = "linux")]
        let errno = unsafe { libc::__errno_location() };
        unsafe { *errno = 0 };
        let entry = unsafe { libc::readdir(reader) };
        if entry.is_null() {
            return (unsafe { *errno } == 0).then_some(names);
        }
        let name = unsafe { CStr::from_ptr((*entry).d_name.as_ptr()) }
            .to_str()
            .ok()?;
        if name != "." && name != ".." {
            if names.len() == 4096 {
                return None;
            }
            names.push(name.to_owned());
        }
    }
}
