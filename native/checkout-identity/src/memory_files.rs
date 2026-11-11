//! owner: MemoryFiles; allowed imports: std/libc/JSON/source-bound memory validators;
//! forbidden imports: writes/providers/lifecycle authority; callers/tests: private
//! memory record/scan queries; verification: real-file, descriptor and source oracles.
use crate::{memory_json::MemoryJson, memory_record::MemoryRecord, memory_terms::MemoryTerms};
use serde_json::{json, Value};
use std::{
    ffi::{CStr, CString},
    fs::{self, File, Metadata},
    io::Read,
    os::unix::{
        ffi::OsStrExt,
        fs::MetadataExt,
        io::{AsRawFd, FromRawFd},
    },
    path::{Component, Path},
};
pub(crate) struct MemoryFiles;
impl MemoryFiles {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        if payload.as_object()?.len() != 2
            || payload.get("unicode")?.as_str()? != MemoryTerms::version()
        {
            return None;
        }
        let path = Path::new(payload.get("path")?.as_str()?);
        match operation {
            "record" => Some(json!({"record":Self::record(path)?})),
            "scan" => Self::scan(path),
            _ => None,
        }
    }
    fn record(path: &Path) -> Option<Option<Value>> {
        let metadata = match fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Some(None),
            Err(_) => return None,
        };
        if metadata.is_symlink() || metadata.is_dir() {
            return Some(None);
        }
        if !metadata.is_file() {
            return None;
        }
        let file = Self::anchor(path, &metadata)?;
        Self::read(file, path.file_name()?.to_str()?)
    }
    fn scan(path: &Path) -> Option<Value> {
        let metadata = match fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Some(json!({"records":[],"unreadable":0}))
            }
            Err(_) => return None,
        };
        if !metadata.is_dir() {
            return Some(json!({"records":[],"unreadable":0}));
        }
        let directory = Self::anchor(path, &metadata)?;
        let names = Self::names(&directory)?;
        let mut records = Vec::new();
        let mut unreadable = 0;
        for name in names {
            match Self::child(&directory, &name)? {
                Some(record) => records.push(record),
                None => unreadable += 1,
            }
        }
        let current = fs::symlink_metadata(path).ok()?;
        if current.dev() != metadata.dev() || current.ino() != metadata.ino() {
            return None;
        }
        Some(json!({"records":records,"unreadable":unreadable}))
    }
    fn read(mut file: File, name: &str) -> Option<Option<Value>> {
        if file.metadata().ok()?.len() > 1024 * 1024 {
            return None;
        }
        let mut bytes = Vec::new();
        if file
            .by_ref()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
        {
            return Some(None);
        }
        if bytes.len() > 1024 * 1024 {
            return None;
        }
        let Some(record) = MemoryJson::decode(&bytes)? else {
            return Some(None);
        };
        Some(MemoryRecord::valid(&record, name)?.then_some(record))
    }
    fn child(directory: &File, name: &str) -> Option<Option<Value>> {
        let name_c = CString::new(name).ok()?;
        let mut stat: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name_c.as_ptr(),
                &mut stat,
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            return if std::io::Error::last_os_error().kind() == std::io::ErrorKind::NotFound {
                Some(None)
            } else {
                None
            };
        }
        let kind = stat.st_mode & libc::S_IFMT;
        if kind == libc::S_IFLNK || kind == libc::S_IFDIR {
            return Some(None);
        }
        if kind != libc::S_IFREG {
            return None;
        }
        let flags =
            libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY;
        let fd = unsafe { libc::openat(directory.as_raw_fd(), name_c.as_ptr(), flags) };
        if fd < 0 {
            return None;
        }
        let file = unsafe { File::from_raw_fd(fd) };
        let actual = file.metadata().ok()?;
        if !actual.is_file()
            || actual.dev() != stat.st_dev as u64
            || actual.ino() != stat.st_ino as u64
        {
            return None;
        }
        Self::read(file, name)
    }
    fn anchor(path: &Path, expected: &Metadata) -> Option<File> {
        let absolute = if path.is_absolute() {
            path.to_owned()
        } else {
            std::env::current_dir().ok()?.join(path)
        };
        let mut file = File::open("/").ok()?;
        let mut parts = absolute.components().peekable();
        let mut prefix = std::path::PathBuf::new();
        while let Some(part) = parts.next() {
            let name = match part {
                Component::RootDir => {
                    prefix.push("/");
                    continue;
                }
                Component::CurDir => continue,
                Component::Normal(name) => name,
                _ => return None,
            };
            prefix.push(name);
            if Self::descriptor(&prefix)? {
                return None;
            }
            let name = CString::new(name.as_bytes()).ok()?;
            let flags = libc::O_RDONLY
                | libc::O_CLOEXEC
                | libc::O_NOFOLLOW
                | libc::O_NONBLOCK
                | libc::O_NOCTTY
                | if parts.peek().is_some() || expected.is_dir() {
                    libc::O_DIRECTORY
                } else {
                    0
                };
            let fd = unsafe { libc::openat(file.as_raw_fd(), name.as_ptr(), flags) };
            if fd < 0 {
                return None;
            }
            file = unsafe { File::from_raw_fd(fd) };
        }
        let actual = file.metadata().ok()?;
        (actual.dev() == expected.dev()
            && actual.ino() == expected.ino()
            && actual.is_file() == expected.is_file()
            && actual.is_dir() == expected.is_dir())
        .then_some(file)
    }
    pub(crate) fn descriptor(path: &Path) -> Option<bool> {
        let mut text = path.to_str()?.to_owned();
        if cfg!(target_os = "macos") {
            text.make_ascii_lowercase();
        }
        let names: Vec<_> = text.split('/').filter(|p| !p.is_empty()).collect();
        Some(
            (names.first() == Some(&"dev")
                && matches!(names.get(1), Some(&"fd" | &"stdin" | &"stdout" | &"stderr")))
                || (names.first() == Some(&"proc")
                    && (names.get(2) == Some(&"fd")
                        || (names.get(2) == Some(&"task") && names.get(4) == Some(&"fd")))),
        )
    }
    fn names(directory: &File) -> Option<Vec<String>> {
        let fd = unsafe { libc::fcntl(directory.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 0) };
        if fd < 0 {
            return None;
        }
        let reader = unsafe { libc::fdopendir(fd) };
        if reader.is_null() {
            unsafe { libc::close(fd) };
            return None;
        }
        let outcome = (|| {
            let mut names = Vec::new();
            loop {
                unsafe { *Self::errno() = 0 };
                let entry = unsafe { libc::readdir(reader) };
                if entry.is_null() {
                    return (unsafe { *Self::errno() } == 0).then(|| {
                        names.sort();
                        names
                    });
                }
                let name = unsafe { CStr::from_ptr((*entry).d_name.as_ptr()) }
                    .to_str()
                    .ok()?;
                if name.ends_with(".json") {
                    names.push(name.to_owned());
                }
            }
        })();
        unsafe { libc::closedir(reader) };
        outcome
    }
    fn errno() -> *mut libc::c_int {
        #[cfg(target_os = "macos")]
        {
            unsafe { libc::__error() }
        }
        #[cfg(target_os = "linux")]
        {
            unsafe { libc::__errno_location() }
        }
    }
}

#[cfg(test)]
#[path = "memory_file_tests.rs"]
mod tests;
