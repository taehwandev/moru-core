//! owner: MemorySource; allowed imports: std/JSON/read-only filesystem/process/profile owners;
//! forbidden imports: memory writes, Git mutations, providers, lifecycle authority;
//! callers/tests: memory blob probe; verification: worktree/index/filter/path oracles.
use crate::{
    discovery_fs::DiscoveryFs, memory_files::MemoryFiles, memory_terms::MemoryTerms,
    python_encoding::PythonEncoding, python_text::PythonText, read_process::capture_raw,
};
use serde_json::{json, Value};
use std::{
    fs,
    path::Path,
    process::{Command, Stdio},
    time::Duration,
};

pub(crate) struct MemorySource;
impl MemorySource {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        if payload.as_object()?.len() != 6
            || payload.get("unicode")?.as_str()? != MemoryTerms::version()
            || payload.get("stdin_eof")?.as_bool()? != true
            || payload.get("encoding")?.as_str()? != "utf-8"
            || !PythonEncoding::utf8()
        {
            return None;
        }
        let root = Path::new(payload.get("root")?.as_str()?);
        let path = payload.get("path")?.as_str()?;
        let tracked = payload.get("tracked")?.as_bool()?;
        if !root.is_absolute() || MemoryFiles::descriptor(root)? {
            return None;
        }
        Self::blob(root, path, tracked)
    }
    fn blob(root: &Path, path: &str, tracked: bool) -> Option<Value> {
        if !Self::valid_path(path) {
            return Some(json!({"blob":""}));
        }
        // The caller already resolved this root in its original process.
        // Unknown/direct protocol roots retain the Python owner.
        if DiscoveryFs::resolve(root)?.as_path() != root {
            return None;
        }
        let candidate = root.join(path);
        let resolved = match DiscoveryFs::resolve(&candidate) {
            Some(resolved) => resolved,
            None => {
                return match fs::symlink_metadata(&candidate) {
                    Err(error)
                        if matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) =>
                    {
                        Some(json!({"blob":""}))
                    }
                    _ => None, // Preserve Python's loop/uncertain-resolution errors.
                }
            }
        };
        // Match strict resolve equality: reject both final and ancestor links.
        if resolved != candidate || !fs::metadata(&candidate).is_ok_and(|m| m.is_file()) {
            return Some(json!({"blob":""}));
        }
        if tracked {
            let checked = capture_raw(
                Command::new("git")
                    .stdin(Stdio::null())
                    .arg("--literal-pathspecs")
                    .arg("-C")
                    .arg(root)
                    .args(["ls-files", "--error-unmatch", "--", path]),
                Duration::from_secs(2),
            )
            .ok()?;
            if !checked.is_some_and(|(_, _, success)| success) {
                return Some(json!({"blob":""}));
            }
        }
        let result = capture_raw(
            Command::new("git")
                .stdin(Stdio::null())
                .arg("-C")
                .arg(root)
                .args(["hash-object", "--no-filters", "--", path]),
            Duration::from_secs(2),
        )
        .ok()?;
        let Some((stdout, stderr, success)) = result else {
            return Some(json!({"blob":""}));
        };
        // Python decodes stdout before stderr even on nonzero exits. Return
        // the failing bytes so the bridge raises the same error without replay.
        for bytes in [&stdout, &stderr] {
            if std::str::from_utf8(bytes).is_err() {
                return Some(json!({"decode_error":bytes}));
            }
        }
        let text = std::str::from_utf8(&stdout).ok()?;
        let blob = text.trim_matches(PythonText::whitespace);
        Some(json!({"blob":if success && Self::valid_blob(blob) {
            blob
        } else {
            ""
        }}))
    }
    fn valid_path(path: &str) -> bool {
        (1..=300).contains(&path.chars().count())
            && path.chars().all(PythonText::printable)
            && !path.contains('\\')
            && path
                .split('/')
                .all(|p| !p.is_empty() && ![".", "..", ".git"].contains(&p))
    }
    fn valid_blob(blob: &str) -> bool {
        matches!(blob.len(), 40 | 64)
            && blob
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    }
}
