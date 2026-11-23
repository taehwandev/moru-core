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
        if let Some(content) = content {
            Some(json!({"signature": signature, "fingerprint": content.finish(root, excluded)?}))
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
                    });
                }
            }
        }
        Some(entries)
    }

    fn hash(digest: &mut Sha256, label: &[u8], value: &[u8]) {
        digest.update((label.len() as u32).to_be_bytes());
        digest.update(label);
        digest.update((value.len() as u64).to_be_bytes());
        digest.update(value);
    }
}
