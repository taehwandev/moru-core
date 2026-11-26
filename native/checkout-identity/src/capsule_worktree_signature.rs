//! owner: read-only Git status scan for execution capsule worktree state.
//! allowed imports: bounded read process, std, SHA-256 and JSON.
//! forbidden imports: workspace mutation, provider calls and evidence authority.
//! callers/tests: completion probe and source-bound Python parity.
//! verification: byte paths, rename framing, partial staging and fallback.
use crate::read_process::status::capture_status;
#[path = "capsule_worktree_content.rs"]
mod content;
use content::WorktreeContent;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsStr,
    fs::{self, Metadata},
    io::ErrorKind,
    os::unix::{ffi::OsStrExt, fs::MetadataExt},
    path::{Component, Path},
    process::{Command, Stdio},
    time::Duration,
};

pub(super) struct WorktreeSignature;

struct Entry<'a> {
    path: &'a [u8],
    record: &'a [u8],
    xy: &'a [u8],
    added: bool,
    untracked: bool,
}

impl WorktreeSignature {
    pub(super) fn capture(payload: &Value) -> Option<Value> {
        let root = Path::new(payload.get("path")?.as_str()?);
        let max_files = usize::try_from(payload.get("max_files")?.as_u64()?).ok()?;
        let max_bytes = payload.get("max_bytes")?.as_u64()?;
        let excluded = match payload.get("excluded") {
            None | Some(Value::Null) => None,
            Some(value) => Some(value.as_str()?),
        };
        let paths: Option<Vec<&str>> = match payload.get("paths") {
            None | Some(Value::Null) => None,
            Some(Value::Array(items)) => {
                let mut list = Vec::with_capacity(items.len());
                for item in items {
                    let value = item.as_str()?.trim();
                    if value.is_empty() {
                        return None;
                    }
                    list.push(value);
                }
                if list.is_empty() { None } else { Some(list) }
            }
            Some(_) => return None,
        };
        let mut content = payload
            .get("strong")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            .then(WorktreeContent::default);
        if !root.is_absolute() || root.canonicalize().ok()?.as_os_str() != root.as_os_str() {
            return None;
        }
        let (stdout, status) = Self::git(
            root,
            &["status", "--porcelain=v2", "-z", "--untracked-files=all"],
            4 * 1024 * 1024,
        )?;
        if status != 0 {
            return None;
        }
        let mut entries = Self::entries(&stdout, excluded.map(str::as_bytes))?;
        // The reference allows a larger budget for all-staged additions on
        // an unborn branch. Let it classify that exceptional case.
        if entries.len() > max_files && entries.iter().all(|entry| entry.xy == b"A.") {
            return None;
        }
        entries.sort_by_key(|entry| entry.path);
        let mut signature = Sha256::new();
        let mut last = None;
        for entry in &entries {
            if last != Some(entry.path) {
                Self::hash(&mut signature, b"status-path", entry.path);
                if let Some(content) = &mut content {
                    content.frame(b"status-path", entry.path);
                }
                last = Some(entry.path);
            }
        }
        let mut files = 0;
        let mut bytes = 0_u64;
        for entry in entries {
            if entry.xy.len() == 2 && !entry.xy.contains(&b'.') {
                Self::hash(&mut signature, b"partial-status", entry.record);
                if let Some(content) = &mut content {
                    content.frame(b"partial-status", entry.record);
                }
            }
            let relative = Path::new(OsStr::from_bytes(entry.path));
            if entry.path.is_empty()
                || !relative
                    .components()
                    .all(|part| matches!(part, Component::Normal(_) | Component::CurDir))
            {
                return None;
            }
            let path = root.join(relative);
            let metadata = match fs::symlink_metadata(&path) {
                Ok(metadata) => metadata,
                Err(err) if err.kind() == ErrorKind::NotFound => {
                    Self::hash(&mut signature, b"worktree-raced", entry.path);
                    if let Some(content) = &mut content {
                        content.frame(b"worktree-raced", entry.path);
                    }
                    continue;
                }
                Err(_) => return None,
            };
            Self::hash(&mut signature, b"worktree-path", entry.path);
            Self::hash(
                &mut signature,
                b"worktree-metadata",
                Self::metadata_key(&metadata).as_bytes(),
            );
            if entry.added {
                let out_of_scope_untracked = entry.untracked
                    && paths
                        .as_deref()
                        .is_some_and(|scoped| !Self::path_in_scope(entry.path, scoped));
                if out_of_scope_untracked {
                    if let Some(content) = &mut content {
                        content.metadata_entry(entry.path, &metadata);
                    }
                    continue;
                }
                files += 1;
                bytes = bytes.checked_add(metadata.size())?;
                if files > max_files || bytes > max_bytes {
                    return None;
                }
                if let Some(content) = &mut content {
                    content.added(&path, entry.path, &metadata, max_bytes)?;
                }
            }
        }
        let signature = format!("{:x}", signature.finalize());
        let scoped = paths.is_some();
        if let Some(content) = content {
            let fingerprint = content.finish(root, excluded)?;
            if scoped {
                Some(json!({"signature": signature, "fingerprint": fingerprint, "scoped": true}))
            } else {
                Some(json!({"signature": signature, "fingerprint": fingerprint}))
            }
        } else if scoped {
            Some(json!({"signature": signature, "scoped": true}))
        } else {
            Some(json!({"signature": signature}))
        }
    }

    pub(super) fn git(root: &Path, args: &[&str], bound: u64) -> Option<(Vec<u8>, i32)> {
        let (stdout, _, status) = capture_status(
            Command::new("git")
                .current_dir(root)
                .env("GIT_OPTIONAL_LOCKS", "0")
                .env("GIT_TERMINAL_PROMPT", "0")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_ALLOW_PROTOCOL", "")
                .args(args)
                .stdin(Stdio::null()),
            Duration::from_secs(6),
            Some(bound),
            None,
        )
        .ok()??;
        Some((stdout, status.code()?))
    }

    fn metadata_key(metadata: &Metadata) -> String {
        let mtime =
            i128::from(metadata.mtime()) * 1_000_000_000 + i128::from(metadata.mtime_nsec());
        let ctime =
            i128::from(metadata.ctime()) * 1_000_000_000 + i128::from(metadata.ctime_nsec());
        format!(
            "{}\0{}\0{mtime}\0{ctime}\0{}\0{}",
            metadata.mode(),
            metadata.size(),
            metadata.dev(),
            metadata.ino()
        )
    }

    fn entries<'a>(bytes: &'a [u8], excluded: Option<&[u8]>) -> Option<Vec<Entry<'a>>> {
        let mut records = bytes
            .split(|byte| *byte == 0)
            .filter(|record| !record.is_empty());
        let mut entries = Vec::new();
        while let Some(record) = records.next() {
            let kind = *record.first()?;
            if kind == b'?' {
                let path = record.get(2..)?;
                if Some(path) != excluded {
                    entries.push(Entry {
                        path,
                        record,
                        xy: b"",
                        added: true,
                        untracked: true,
                    });
                }
                continue;
            }
            let field_count = match kind {
                b'1' => 9,
                b'2' => 10,
                b'u' => 11,
                _ => return None,
            };
            let fields: Vec<_> = record.splitn(field_count, |byte| *byte == b' ').collect();
            if fields.len() != field_count {
                return None;
            }
            let path = fields[field_count - 1];
            if Some(path) != excluded {
                if kind != b'u' && fields[2].starts_with(b"S") && fields[2] != b"S..." {
                    return None;
                }
                let xy = fields[1];
                entries.push(Entry {
                    path,
                    record,
                    xy,
                    added: kind == b'2' || xy.contains(&b'A'),
                    untracked: false,
                });
            }
            if kind == b'2' {
                // The original path is a distinct rename deletion observation,
                // even when the destination record was excluded.
                let source = records.next()?;
                if fields[8].starts_with(b"R") {
                    entries.push(Entry {
                        path: source,
                        record: b"",
                        xy: b"",
                        added: false,
                        untracked: false,
                    });
                }
            }
        }
        Some(entries)
    }

    fn path_in_scope(raw_path: &[u8], scoped: &[&str]) -> bool {
        let rel = String::from_utf8_lossy(raw_path).replace('\\', "/");
        let rel = rel.trim_start_matches("./");
        for item in scoped {
            let norm = item
                .replace('\\', "/")
                .trim()
                .trim_start_matches("./")
                .trim_end_matches('/')
                .to_owned();
            if norm.is_empty() || norm == "." {
                return true;
            }
            if rel == norm
                || (rel.starts_with(&norm) && rel.as_bytes().get(norm.len()) == Some(&b'/'))
            {
                return true;
            }
        }
        false
    }

    fn hash(digest: &mut Sha256, label: &[u8], value: &[u8]) {
        digest.update((label.len() as u32).to_be_bytes());
        digest.update(label);
        digest.update((value.len() as u64).to_be_bytes());
        digest.update(value);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn pathspec_capture_ignores_out_of_scope_oversized_untracked_files() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("moru-c5-test-{stamp}"));
        fs::create_dir_all(dir.join("src")).unwrap();
        fs::create_dir_all(dir.join("renders")).unwrap();
        fs::write(dir.join("tracked.txt"), "base\n").unwrap();
        let run = |args: &[&str]| {
            let status = Command::new("git")
                .current_dir(&dir)
                .args(args)
                .status()
                .unwrap();
            assert!(status.success(), "git {args:?} failed");
        };
        run(&["init", "-q"]);
        run(&["config", "user.email", "tests@example.invalid"]);
        run(&["config", "user.name", "Tests"]);
        run(&["add", "-A"]);
        run(&["commit", "-qm", "init"]);

        fs::write(dir.join("src/a.js"), "export const a = 1;\n").unwrap();
        fs::write(dir.join("renders/frame.bin"), vec![b'x'; 512]).unwrap();
        let root = dir.canonicalize().unwrap();

        let scoped = WorktreeSignature::capture(&json!({
            "path": root.to_str().unwrap(),
            "max_files": 5000,
            "max_bytes": 128,
            "strong": true,
            "paths": ["src/a.js"],
        }));
        let value = scoped.expect("pathspec-scoped capture must ignore out-of-scope renders");
        assert_eq!(value.get("scoped"), Some(&Value::Bool(true)));
        let orig_fp = value
            .get("fingerprint")
            .and_then(Value::as_str)
            .expect("fingerprint")
            .to_owned();
        let orig_sig = value
            .get("signature")
            .and_then(Value::as_str)
            .expect("signature")
            .to_owned();

        // Negative control: editing an out-of-scope tracked file MUST invalidate both signature and fingerprint!
        fs::write(dir.join("tracked.txt"), "mutated out of scope\n").unwrap();
        let after_edit = WorktreeSignature::capture(&json!({
            "path": root.to_str().unwrap(),
            "max_files": 5000,
            "max_bytes": 128,
            "strong": true,
            "paths": ["src/a.js"],
        }))
        .expect("capture after out-of-scope tracked edit");
        assert_ne!(after_edit.get("fingerprint").and_then(Value::as_str), Some(orig_fp.as_str()));
        assert_ne!(after_edit.get("signature").and_then(Value::as_str), Some(orig_sig.as_str()));
        fs::write(dir.join("tracked.txt"), "base\n").unwrap();

        // Negative control: unscoped capture still declines over max_bytes.
        let unscoped = WorktreeSignature::capture(&json!({
            "path": root.to_str().unwrap(),
            "max_files": 5000,
            "max_bytes": 128,
            "strong": true,
        }));
        assert!(unscoped.is_none());

        // Negative control: oversized in-scope path still declines.
        let oversized_in_scope = WorktreeSignature::capture(&json!({
            "path": root.to_str().unwrap(),
            "max_files": 5000,
            "max_bytes": 128,
            "strong": true,
            "paths": ["renders/frame.bin"],
        }));
        assert!(oversized_in_scope.is_none());

        let _ = fs::remove_dir_all(&dir);
    }
}
