//! owner: release selection and guarded removal of released or expired claims.
//! allowed imports: descriptor-relative reads, removals and Python JSON parsing.
//! forbidden imports: claim acquisition, lifecycle policy and network.
//! callers/tests: path_claims.release and test_path_claims.
//! verification: holder recheck, missing entries and no replay after mutation.
use super::{path_claim_filename::PathClaimFilename, path_claim_scan::PathClaimScan};
use crate::{atomic_sibling::AtomicSibling, python_json::PythonJson};
use serde_json::{json, Value};
use std::{
    ffi::{CStr, CString},
    fs::{File, Metadata},
    io::{self, Read},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

pub(super) struct PathClaimRelease;

impl PathClaimRelease {
    pub(super) fn release_selected(input: &Value) -> Option<io::Result<Value>> {
        let result = PathClaimScan::probe(input)?;
        let release = result.get("release")?;
        let wall_clock = SystemTime::now().duration_since(UNIX_EPOCH).ok()?;
        let now = wall_clock.as_secs_f64() + input.get("clock_offset")?.as_f64()?;
        let plan = release.get("plan")?;
        let owned = plan.get("owned")?.as_array()?;
        let receipt = json!({"refused": plan.get("refused")?});
        if release["earliest"]
            .as_f64()
            .is_some_and(|expiry| expiry <= now)
        {
            return None;
        }
        if owned.is_empty() {
            return Some(Ok(receipt));
        }
        let request = json!({
            "project": input.get("project")?,
            "holder": input.get("release")?.get("holder")?,
            "digit_limit": input.get("digit_limit")?,
            "paths": owned,
        });
        Some(Self::release(&request)?.map(|()| receipt))
    }

    pub(super) fn expire(input: &Value) -> Option<io::Result<Option<String>>> {
        let project = Path::new(input.get("project")?.as_str()?);
        let name = input.get("name")?.as_str()?;
        if !name.ends_with(".json") || Path::new(name).file_name()?.to_str()? != name {
            return None;
        }
        let name = CString::new(name).ok()?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let now = input.get("now")?.as_f64()?;
        let directory = AtomicSibling::open_directory(&project.join(".moru/claims"))?;
        let Some(file) = Self::open(&directory, &name).ok()? else {
            return Some(Ok(None));
        };
        let (before, raw) = Self::read(&file)?;
        let modern_iso = input.get("modern_iso").and_then(Value::as_bool) == Some(true);
        if PathClaimScan::parse(&raw, limit, modern_iso)?.is_some_and(|(expiry, _)| expiry > now) {
            return Some(Ok(Some(raw)));
        }
        match Self::unlink(&directory, &name, &before) {
            Ok(true) => Some(Ok(None)),
            // Nothing was removed because the name now resolves to another file.
            Ok(false) => None,
            Err(error) => Some(Err(error)),
        }
    }

    pub(super) fn release(input: &Value) -> Option<io::Result<()>> {
        let project = Path::new(input.get("project")?.as_str()?);
        let holder = input.get("holder")?.as_str()?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let legacy = input.get("names");
        let values = legacy.or_else(|| input.get("paths"))?.as_array()?;
        if values.len() > 1024 {
            return None;
        }
        let names = values
            .iter()
            .map(|value| {
                let value = value.as_str()?;
                if legacy.is_some() {
                    PathClaimFilename::legacy(value)
                } else {
                    PathClaimFilename::derive(value)
                }
            })
            .collect::<Option<Vec<_>>>()?;
        let directory = AtomicSibling::open_directory(&project.join(".moru/claims"))?;
        let mut pending = Vec::new();
        for name in names {
            let Some(file) = Self::open(&directory, &name).ok()? else {
                continue;
            };
            let (before, raw) = Self::read(&file)?;
            let claim = PythonJson::parse_with_diagnostic(&raw, Some(limit), None).ok()??;
            if claim.get("holder").and_then(|value| value.as_str()) == Some(holder) {
                pending.push((name, before));
            }
        }
        // Never report a replayable decline after starting the removal pass.
        Some(
            pending
                .iter()
                .try_for_each(|(name, before)| Self::unlink(&directory, name, before).map(|_| ())),
        )
    }

    fn read(file: &File) -> Option<(Metadata, String)> {
        let before = file.metadata().ok()?;
        if !before.is_file() {
            return None;
        }
        let mut raw = String::new();
        file.take(64 * 1024 + 1).read_to_string(&mut raw).ok()?;
        (raw.len() <= 64 * 1024).then_some((before, raw))
    }

    fn open(directory: &File, name: &CStr) -> io::Result<Option<File>> {
        match AtomicSibling::open_relative_result(directory, name, libc::O_RDONLY) {
            Ok(file) => Ok(Some(file)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn unlink(directory: &File, name: &CStr, before: &Metadata) -> io::Result<bool> {
        let Some(file) = Self::open(directory, name)? else {
            return Ok(true);
        };
        let current = file.metadata()?;
        if before.dev() != current.dev()
            || before.ino() != current.ino()
            || before.len() != current.len()
            || before.mtime() != current.mtime()
            || before.mtime_nsec() != current.mtime_nsec()
        {
            return Ok(false);
        }
        if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) } == 0 {
            return Ok(true);
        }
        let error = io::Error::last_os_error();
        if error.kind() == io::ErrorKind::NotFound {
            return Ok(true);
        }
        Err(error)
    }
}
