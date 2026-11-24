//! owner: one exclusive path-claim creation or same-holder renewal.
//! allowed imports: anchored filesystem I/O and Python JSON.
//! forbidden imports: multi-claim scheduling, authority decisions and network.
//! callers/tests: path_claims._write_claim, test_path_claims.
//! verification: byte/mode parity, collision handling and write receipt contract.
use super::path_claim_filename::PathClaimFilename;
use crate::{
    atomic_sibling::AtomicSibling,
    overhead_clock::OverheadClock,
    python_json::{Object, PythonJson, Value},
};
use serde_json::{json, Value as Json};
use std::{
    ffi::{CStr, CString},
    fs::File,
    io::{self, Read, Write},
    path::Path,
    time::Instant,
};

pub(super) struct PathClaimWrite;

impl PathClaimWrite {
    pub(super) fn batch(input: &Json) -> Option<io::Result<Json>> {
        let project = input.get("project")?.as_str()?;
        let holder = input.get("holder")?.as_str()?;
        let ttl = input.get("ttl")?.as_i64()?;
        let now = input.get("now")?.as_f64()?;
        let digit_limit = input.get("digit_limit")?.as_u64()?;
        let paths = input.get("paths")?.as_array()?;
        if paths.is_empty() || paths.len() > 128 {
            return None;
        }
        let paths = paths.iter().map(Json::as_str).collect::<Option<Vec<_>>>()?;
        // Advance the caller's wall-clock sample between writes using elapsed time.
        let started = Instant::now();
        for (index, path) in paths.iter().enumerate() {
            let result = Self::write(&json!({
                "project": project, "digit_limit": digit_limit,
                "now": now + started.elapsed().as_secs_f64(), "ttl": ttl,
                "entry": {"path": path, "holder": holder},
            }));
            match result {
                Some(Ok(true)) => {}
                Some(Ok(false)) => return Some(Ok(json!({"written": index, "blocked": true}))),
                Some(Err(error)) => return Some(Err(error)),
                None if index == 0 => return None,
                None => return Some(Ok(json!({"written": index, "blocked": false}))),
            }
        }
        Some(Ok(json!({"written": paths.len(), "blocked": false})))
    }

    // None means that no claim file was created or replaced.
    pub(super) fn write(input: &Json) -> Option<io::Result<bool>> {
        let project = Path::new(input.get("project")?.as_str()?);
        let entry = input.get("entry")?;
        let target = match input.get("name") {
            Some(name) => PathClaimFilename::legacy(name.as_str()?)?,
            None => PathClaimFilename::derive(entry.get("path")?.as_str()?)?,
        };
        let holder = entry.get("holder")?.as_str()?;
        let mut claim = Object::new();
        for key in ["path", "holder"] {
            claim.insert(key.into(), Value::String(entry.get(key)?.as_str()?.into()));
        }
        let (since, expires) = if let Some(now) = input.get("now") {
            let now = now.as_f64()?;
            let ttl = input.get("ttl")?.as_i64()?;
            (
                OverheadClock::utc_seconds(now)?,
                OverheadClock::utc_seconds(now + ttl as f64)?,
            )
        } else {
            (
                entry.get("since")?.as_str()?.into(),
                entry.get("expires")?.as_str()?.into(),
            )
        };
        claim.insert("since".into(), Value::String(since));
        claim.insert("expires".into(), Value::String(expires));
        let original = PythonJson::render(&Value::Object(claim.clone()), false, true)?;
        let digit_limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let root = AtomicSibling::open_directory(project)?;
        let local = AtomicSibling::ensure_directory(&root, c".moru")?;
        let directory = AtomicSibling::ensure_directory(&local, c"claims")?;
        let flags = libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL;
        match AtomicSibling::open_relative_with_mode(&directory, &target, flags, 0o644) {
            Ok(mut file) => Some(file.write_all(original.as_bytes()).map(|_| true)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                Self::renew(&directory, &target, holder, claim, digit_limit)
            }
            Err(_) => None,
        }
    }

    fn renew(
        directory: &File,
        target: &CStr,
        holder: &str,
        mut claim: Object,
        digit_limit: usize,
    ) -> Option<io::Result<bool>> {
        let file = AtomicSibling::open_relative(directory, target, libc::O_RDONLY)?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut raw = String::new();
        file.take(64 * 1024 + 1).read_to_string(&mut raw).ok()?;
        if raw.len() > 64 * 1024 {
            return None;
        }
        let current = PythonJson::parse_with_diagnostic(&raw, Some(digit_limit), None).ok()??;
        if !current.is_object() {
            return None;
        }
        if current.get("holder").and_then(Value::as_str) != Some(holder) {
            return Some(Ok(false));
        }
        if let Some(since) = current.get("since") {
            claim.insert("since".into(), since.clone());
        }
        let updated = PythonJson::render(&Value::Object(claim), false, true)?;
        let stem = target.to_str().ok()?.strip_suffix(".json")?;
        let temporary = CString::new(format!("{stem}.{}.tmp", std::process::id())).ok()?;
        Some(
            AtomicSibling::InheritUmask
                .replace(directory, &temporary, target, updated.as_bytes())
                .map(|_| true),
        )
    }
}
