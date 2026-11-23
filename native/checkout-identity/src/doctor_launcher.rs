//! owner: read-only installed launcher checks for doctor.
//! allowed imports: guarded file reads, Python text normalization, SHA-256 and JSON.
//! forbidden imports: installer, filesystem writes, process execution and policy mutations.
//! callers/tests: completion probe and installed fixture parity tests.
//! verification: launcher-first warnings, execute mode, digest and root-pointer text.
use crate::text::Text;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    env,
    ffi::CString,
    fs::{self, File},
    io::{Read, Take},
    os::unix::{ffi::OsStrExt, fs::OpenOptionsExt},
    path::Path,
};

pub(super) struct DoctorLauncher;

impl DoctorLauncher {
    pub(super) fn inspect(payload: &Value) -> Option<Value> {
        let home = env::var_os("HOME")?;
        let home = Path::new(&home);
        if !home.is_absolute() {
            return None;
        }
        let expected_text = payload.get("launcher_text")?.as_str()?;
        let expected_pointer = payload.get("pointer_text")?.as_str()?;
        let expected_digest = payload.get("binary_sha256")?.as_str()?;
        let launcher = home.join(".moru/bin/moru-hook");
        let binary = launcher.with_file_name("moru-hook-native");
        let pointer = home.join(".moru/moru-root");
        let issue = if !launcher.try_exists().ok()?
            || Self::read_text(&launcher, 256 * 1024)? != expected_text
            || !Self::executable(&launcher)?
            || !Self::installed_matches(&binary, expected_digest)?
        {
            "launcher"
        } else if Self::read_text(&pointer, 4096)? != expected_pointer {
            "pointer"
        } else {
            ""
        };
        Some(json!({"issue": issue}))
    }

    fn read_text(path: &Path, limit: u64) -> Option<String> {
        let mut reader = Self::bounded_file(path, limit)?;
        let mut text = String::new();
        reader.read_to_string(&mut text).ok()?;
        (reader.limit() != 0).then(|| Text::universal_newlines(&text))
    }

    fn installed_matches(path: &Path, expected: &str) -> Option<bool> {
        if !path.try_exists().ok()?
            || fs::symlink_metadata(path).ok()?.is_symlink()
            || !Self::executable(path)?
        {
            return Some(false);
        }
        let mut reader = Self::bounded_file(path, 256 * 1024 * 1024)?;
        let mut hash = Sha256::new();
        let mut buffer = [0; 32 * 1024];
        loop {
            let length = reader.read(&mut buffer).ok()?;
            if length == 0 {
                break;
            }
            hash.update(&buffer[..length]);
        }
        (reader.limit() != 0).then(|| format!("{:x}", hash.finalize()) == expected)
    }

    fn bounded_file(path: &Path, limit: u64) -> Option<Take<File>> {
        let named = fs::symlink_metadata(path).ok()?;
        if !named.is_file() || named.len() > limit {
            return None;
        }
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(path)
            .ok()?;
        file.metadata()
            .ok()?
            .is_file()
            .then(|| file.take(limit + 1))
    }

    fn executable(path: &Path) -> Option<bool> {
        let raw = CString::new(path.as_os_str().as_bytes()).ok()?;
        Some(path.is_file() && unsafe { libc::access(raw.as_ptr(), libc::X_OK) } == 0)
    }
}
