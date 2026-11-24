//! owner: guarded removal of selected path claim files.
//! allowed imports: descriptor-relative reads, removals and Python JSON parsing.
//! forbidden imports: path selection, lifecycle policy and network.
//! callers/tests: path_claims.release and test_path_claims.
//! verification: holder recheck, missing entries and no replay after mutation.
use crate::{atomic_sibling::AtomicSibling, python_json::PythonJson};
use serde_json::Value;
use std::{
    ffi::{CStr, CString},
    fs::{File, Metadata},
    io::{self, Read},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
};

pub(super) struct PathClaimRelease;

impl PathClaimRelease {
    pub(super) fn release(input: &Value) -> Option<io::Result<()>> {
        let project = Path::new(input.get("project")?.as_str()?);
        let holder = input.get("holder")?.as_str()?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let names = input.get("names")?.as_array()?;
        if names.len() > 1024 {
            return None;
        }
        let names = names.iter().map(Self::name).collect::<Option<Vec<_>>>()?;
        let directory = AtomicSibling::open_directory(&project.join(".moru/claims"))?;
        let mut pending = Vec::new();
        for name in names {
            let Some(file) = Self::open(&directory, &name).ok()? else {
                continue;
            };
            let before = file.metadata().ok()?;
            if !before.is_file() {
                return None;
            }
            let mut raw = String::new();
            (&file).take(64 * 1024 + 1).read_to_string(&mut raw).ok()?;
            if raw.len() > 64 * 1024 {
                return None;
            }
            let claim = PythonJson::parse_with_diagnostic(&raw, Some(limit), None).ok()??;
            if claim.get("holder").and_then(|value| value.as_str()) == Some(holder) {
                pending.push((name, before));
            }
        }
        // Never report a replayable decline after starting the removal pass.
        Some(
            pending
                .iter()
                .try_for_each(|(name, before)| Self::unlink(&directory, name, before)),
        )
    }

    fn name(value: &Value) -> Option<CString> {
        let name = value.as_str()?;
        let hash = name.strip_suffix(".json")?;
        (hash.len() == 40
            && hash
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
        .then(|| CString::new(name).ok())
        .flatten()
    }

    fn open(directory: &File, name: &CStr) -> io::Result<Option<File>> {
        match AtomicSibling::open_relative_result(directory, name, libc::O_RDONLY) {
            Ok(file) => Ok(Some(file)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn unlink(directory: &File, name: &CStr, before: &Metadata) -> io::Result<()> {
        let Some(file) = Self::open(directory, name)? else {
            return Ok(());
        };
        let current = file.metadata()?;
        if before.dev() != current.dev()
            || before.ino() != current.ino()
            || before.len() != current.len()
            || before.mtime() != current.mtime()
            || before.mtime_nsec() != current.mtime_nsec()
        {
            return Ok(());
        }
        if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) } == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        if error.kind() == io::ErrorKind::NotFound {
            return Ok(());
        }
        Err(error)
    }
}
