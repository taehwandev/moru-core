//! owner: FigmaFile; allowed imports: bounded regular-file IO, libc, PythonText;
//! forbidden imports: stream/device reads, writes, Python execution;
//! callers/tests: FigmaProcess; verification: original-path errno diagnostics and safe deferral.
use crate::python_text::PythonText;
#[path = "figma_file_outcome.rs"]
mod outcome;
pub(super) use outcome::FileRead;
use std::{
    collections::VecDeque,
    ffi::{CStr, OsString},
    fs,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Component, Path, PathBuf},
};
pub(super) struct FigmaFile;
impl FigmaFile {
    pub(super) fn read(path: &OsString) -> Option<FileRead> {
        const LIMIT: u64 = 64 * 1024 * 1024;
        let original = Path::new(path);
        let lexical = if original.is_absolute() {
            original.to_owned()
        } else {
            std::env::current_dir().ok()?.join(original)
        };
        if Self::through_descriptor(&lexical) {
            return None;
        }
        // Check the original spelling first: file/ must retain ENOTDIR, not resolve to file.
        let before = match fs::metadata(original) {
            Ok(meta) => meta,
            Err(error) => return Self::lookup_error(path, error),
        };
        if (!before.is_file() && !before.is_dir()) || before.len() > LIMIT {
            return None;
        }
        let canonical = fs::canonicalize(original).ok()?;
        if Self::descriptor_path(&canonical) {
            return None;
        }
        let resolved = fs::metadata(&canonical).ok()?;
        if !Self::same(&before, &resolved) {
            return None;
        }
        let file = match fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW)
            .open(&canonical)
        {
            Ok(file) => file,
            Err(error) => {
                // O_NOFOLLOW can manufacture ELOOP after a concurrent replacement.
                // Only stable access refusals are equivalent to opening the original name.
                if !matches!(error.raw_os_error(), Some(libc::EACCES | libc::EPERM)) {
                    return None;
                }
                if !Self::same(&before, &fs::metadata(original).ok()?)
                    || !Self::same(&before, &fs::symlink_metadata(&canonical).ok()?)
                {
                    return None;
                }
                return Self::error(path, error.raw_os_error()?);
            }
        };
        let opened = file.metadata().ok()?;
        if !Self::same(&before, &opened) {
            return None;
        }
        if opened.is_dir() {
            return Self::error(path, libc::EISDIR);
        }
        if !opened.is_file() {
            return None;
        }
        let mut bytes = Vec::new();
        file.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        (bytes.len() as u64 <= LIMIT).then_some(FileRead::Bytes(bytes))
    }

    fn descriptor_path(path: &Path) -> bool {
        path.starts_with("/dev") || path.starts_with("/proc")
    }
    fn through_descriptor(path: &Path) -> bool {
        // Inspect link text before classifying lookup errors: a dangling alias
        // into /dev/fd must remain deferred even though canonicalize cannot see it.
        let mut pending: VecDeque<_> = path
            .components()
            .map(|c| c.as_os_str().to_owned())
            .collect();
        let mut current = PathBuf::new();
        let mut links = 0;
        while let Some(part) = pending.pop_front() {
            match Path::new(&part).components().next() {
                Some(Component::ParentDir) => {
                    current.pop();
                }
                Some(Component::CurDir) => {}
                _ => current.push(&part),
            }
            if Self::descriptor_path(&current) {
                return true;
            }
            if let Ok(target) = fs::read_link(&current) {
                links += 1;
                if links > 40 {
                    return false;
                } // Kernel lookup fails before consuming a stream.
                current.pop();
                let mut replacement: VecDeque<_> = target
                    .components()
                    .map(|c| c.as_os_str().to_owned())
                    .collect();
                replacement.append(&mut pending);
                pending = replacement;
            }
        }
        false
    }
    fn same(left: &fs::Metadata, right: &fs::Metadata) -> bool {
        left.dev() == right.dev() && left.ino() == right.ino() && left.mode() == right.mode()
    }
    fn lookup_error(path: &OsString, error: std::io::Error) -> Option<FileRead> {
        let errno = error.raw_os_error()?;
        if fs::metadata(path).err()?.raw_os_error()? != errno {
            return None;
        }
        Self::error(path, errno)
    }
    fn error(path: &OsString, errno: i32) -> Option<FileRead> {
        if !matches!(
            errno,
            libc::ENOENT
                | libc::ENOTDIR
                | libc::EISDIR
                | libc::EACCES
                | libc::EPERM
                | libc::ELOOP
                | libc::ENAMETOOLONG
        ) {
            return None;
        }
        let path = path.to_str()?;
        let pointer = unsafe { libc::strerror(errno) };
        if pointer.is_null() {
            return None;
        }
        let message = unsafe { CStr::from_ptr(pointer) }.to_str().ok()?;
        Some(FileRead::Error(format!(
            "ERROR: cannot read summary: [Errno {errno}] {message}: {}\n",
            PythonText::repr(path)
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn errors_use_original_unicode_repr_and_decline_unmodeled_errno() {
        let path = OsString::from("./missing '한글'.json");
        let Some(FileRead::Error(message)) = FigmaFile::error(&path, libc::ENOENT) else {
            panic!("missing error");
        };
        assert!(message.ends_with(": \"./missing '한글'.json\"\n"));
        assert!(FigmaFile::error(&path, libc::EIO).is_none());
    }
}
