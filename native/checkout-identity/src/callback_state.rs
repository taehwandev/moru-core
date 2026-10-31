//! Bounded read-only local state and existing Python-compatible locks.
use std::{
    fs::{self, File},
    io::Read,
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
    path::Path,
};

pub(crate) struct LocalState;

impl LocalState {
    pub(crate) fn absent_dir(path: &Path) -> Option<bool> {
        match fs::symlink_metadata(path) {
            Ok(meta) if meta.is_dir() => Some(false),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Some(true),
            _ => None,
        }
    }

    pub(crate) fn safe_path(base: &Path, path: &Path) -> Option<()> {
        let mut current = base.to_owned();
        for part in
            std::iter::once(None).chain(path.strip_prefix(base).ok()?.components().map(Some))
        {
            if let Some(part) = part {
                current.push(part);
            }
            match fs::symlink_metadata(&current) {
                Ok(meta) if !meta.file_type().is_symlink() => {}
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                _ => return None,
            }
        }
        Some(())
    }

    pub(crate) fn empty(path: &Path) -> Option<()> {
        if Self::absent_dir(path)? {
            return Some(());
        }
        fs::read_dir(path).ok()?.next().is_none().then_some(())
    }

    pub(crate) fn lock(path: &Path) -> Option<File> {
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .ok()?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        (unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0)
            .then_some(file)
    }

    pub(crate) fn read(path: &Path, limit: u64) -> Option<String> {
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .ok()?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut text = String::new();
        file.take(limit + 1).read_to_string(&mut text).ok()?;
        (text.len() as u64 <= limit).then_some(text)
    }
}
