//! owner: read-only non-Git directory state for execution capsules.
//! allowed imports: guarded local reads, std, serde JSON and SHA-256.
//! forbidden imports: filesystem mutation, evidence admission and providers.
//! callers/tests: completion probe and native directory parity fixtures.
//! verification: ordered metadata/content digests, exclusion and reuse.
use crate::atomic_sibling::AtomicSibling;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::{CString, OsStr},
    fs::{self, File, Metadata},
    io::{ErrorKind, Read},
    os::unix::{ffi::OsStrExt, fs::MetadataExt},
    path::Path,
};

const MAX_FILES: usize = 10_000;
const MAX_BYTES: u64 = 512 * 1024 * 1024;
const MAX_ENTRIES: usize = 32_768;
const HEAD: &str = "non-git-directory-v1";

pub(super) struct CapsuleDirectory;

impl CapsuleDirectory {
    pub(super) fn matches_record(path: &Path, recorded: &Value) -> Option<()> {
        if recorded.get("head")?.as_str()? != HEAD || !Self::no_git_marker(path) {
            return None;
        }
        let capture = Self::capture(&json!({
            "path": path.to_str()?,
            "recorded_signature": recorded.get("worktree_signature")?.as_str()?,
        }))?;
        let matches = capture.get("reused").and_then(Value::as_bool) == Some(true)
            || capture.get("state")?.get("worktree_fingerprint")?
                == recorded.get("worktree_fingerprint")?;
        (matches && Self::no_git_marker(path)).then_some(())
    }

    fn no_git_marker(path: &Path) -> bool {
        path.ancestors().all(|ancestor| {
            matches!(
                fs::symlink_metadata(ancestor.join(".git")),
                Err(error) if error.kind() == ErrorKind::NotFound
            )
        })
    }

    pub(super) fn capture(payload: &Value) -> Option<Value> {
        let root = Path::new(payload.get("path")?.as_str()?);
        if !root.is_absolute() || root.canonicalize().ok()?.as_os_str() != root.as_os_str() {
            return None;
        }
        let initial = Walk::capture(root, false)?.signature.finalize();
        let signature = format!("{initial:x}");
        if payload.get("recorded_signature").and_then(Value::as_str) == Some(signature.as_str()) {
            return Some(json!({"reused": true}));
        }
        for _ in 0..2 {
            let captured = Walk::capture(root, true)?;
            let signature = captured.signature.finalize();
            if Walk::capture(root, false)?.signature.finalize() == signature {
                return Some(json!({"state": {
                    "head": HEAD,
                    "worktree_fingerprint": format!("{:x}", captured.fingerprint?.finalize()),
                    "worktree_signature": format!("{signature:x}"),
                }}));
            }
        }
        None
    }
}

struct Walk {
    fingerprint: Option<Sha256>,
    signature: Sha256,
    files: usize,
    entries: usize,
    stated_bytes: u64,
    read_bytes: u64,
}

impl Walk {
    fn capture(root: &Path, strong: bool) -> Option<Self> {
        let mut walk = Self {
            fingerprint: strong.then(Sha256::new),
            signature: Sha256::new(),
            files: 0,
            entries: 0,
            stated_bytes: 0,
            read_bytes: 0,
        };
        walk.visit(root, root, 0)?;
        Some(walk)
    }

    fn visit(&mut self, root: &Path, current: &Path, depth: usize) -> Option<()> {
        if depth > 64 {
            return None;
        }
        let dir = AtomicSibling::open_directory(current)?;
        let identity = dir.metadata().ok()?;
        if !Self::same_inode(&identity, &fs::symlink_metadata(current).ok()?) {
            return None;
        }
        let mut entries = Vec::new();
        for entry in fs::read_dir(current).ok()? {
            self.entries += 1;
            if self.entries > MAX_ENTRIES {
                return None;
            }
            let entry = entry.ok()?;
            let name = entry.file_name();
            name.to_str()?;
            entries.push(name);
        }
        entries.sort();
        for name in entries {
            let candidate = current.join(&name);
            let metadata = fs::symlink_metadata(&candidate).ok()?;
            if metadata.is_dir() && Self::excluded_dir(name.to_str()?, depth == 0)
                || metadata.is_file() && Self::excluded_file(&name)
            {
                continue;
            }
            let relative = candidate.strip_prefix(root).ok()?.as_os_str().as_bytes();
            Self::hash(&mut self.signature, b"directory-path", relative);
            Self::hash(
                &mut self.signature,
                b"directory-metadata",
                Self::metadata(&metadata).as_bytes(),
            );
            if metadata.is_dir() {
                self.visit(root, &candidate, depth + 1)?;
            } else {
                self.content(&dir, &candidate, &name, relative, &metadata)?;
            }
        }
        Self::same_inode(&identity, &fs::symlink_metadata(current).ok()?).then_some(())
    }

    fn content(
        &mut self,
        dir: &File,
        candidate: &Path,
        name: &OsStr,
        relative: &[u8],
        meta: &Metadata,
    ) -> Option<()> {
        self.files += 1;
        self.stated_bytes = self.stated_bytes.checked_add(meta.size())?;
        if self.files > MAX_FILES || self.stated_bytes > MAX_BYTES {
            return None;
        }
        let Some(digest) = &mut self.fingerprint else {
            return Some(());
        };
        Self::hash(digest, b"directory-path", relative);
        Self::hash(
            digest,
            b"directory-mode",
            (meta.mode() & 0o7777).to_string().as_bytes(),
        );
        if meta.file_type().is_symlink() {
            let target = fs::read_link(candidate).ok()?;
            let target = target.as_os_str().as_bytes();
            self.read_bytes = self.read_bytes.checked_add(target.len() as u64)?;
            if self.read_bytes > MAX_BYTES
                || Self::metadata(meta) != Self::metadata(&fs::symlink_metadata(candidate).ok()?)
            {
                return None;
            }
            Self::hash(digest, b"directory-symlink", target);
        } else if meta.is_file() {
            let name = CString::new(name.as_bytes()).ok()?;
            let file = AtomicSibling::open_relative(dir, &name, libc::O_RDONLY)?;
            if Self::metadata(meta) != Self::metadata(&file.metadata().ok()?) {
                return None;
            }
            let available = MAX_BYTES - self.read_bytes;
            let mut limited = file.take(available + 1);
            let mut body = Sha256::new();
            let size = std::io::copy(&mut limited, &mut body).ok()?;
            if size > available
                || Self::metadata(meta) != Self::metadata(&limited.get_ref().metadata().ok()?)
            {
                return None;
            }
            self.read_bytes += size;
            Self::hash(
                digest,
                b"directory-content-size",
                size.to_string().as_bytes(),
            );
            Self::hash(digest, b"directory-content-sha256", &body.finalize());
        } else {
            Self::hash(
                digest,
                b"directory-special",
                meta.mode().to_string().as_bytes(),
            );
        }
        Some(())
    }

    fn same_inode(left: &Metadata, right: &Metadata) -> bool {
        right.is_dir() && left.dev() == right.dev() && left.ino() == right.ino()
    }

    fn metadata(meta: &Metadata) -> String {
        let mtime = i128::from(meta.mtime()) * 1_000_000_000 + i128::from(meta.mtime_nsec());
        let ctime = i128::from(meta.ctime()) * 1_000_000_000 + i128::from(meta.ctime_nsec());
        format!(
            "{}\0{}\0{mtime}\0{ctime}\0{}\0{}",
            meta.mode(),
            meta.size(),
            meta.dev(),
            meta.ino()
        )
    }

    fn hash(digest: &mut Sha256, label: &[u8], value: &[u8]) {
        digest.update((label.len() as u32).to_be_bytes());
        digest.update(label);
        digest.update((value.len() as u64).to_be_bytes());
        digest.update(value);
    }

    fn excluded_dir(name: &str, root: bool) -> bool {
        matches!(
            name,
            ".moru"
                | ".git"
                | ".mypy_cache"
                | ".pytest_cache"
                | ".ruff_cache"
                | ".vibeguard"
                | ".wikimap"
                | "__pycache__"
                | "node_modules"
        ) || root && name == "local"
    }

    fn excluded_file(name: &OsStr) -> bool {
        matches!(name.to_str(), Some(".DS_Store" | ".coverage"))
            || matches!(
                Path::new(name).extension().and_then(OsStr::to_str),
                Some("log" | "pyc" | "pyo")
            )
    }
}
