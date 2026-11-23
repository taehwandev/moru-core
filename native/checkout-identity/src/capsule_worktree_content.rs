//! owner: added file and Git diff components of the capsule fingerprint.
//! allowed imports: guarded file reads, bounded Git reads, std and SHA-256.
//! forbidden imports: writes, provider calls and evidence authorization.
//! callers/tests: worktree status capture and reference parity fixtures.
//! verification: original length-prefixed binary and symlink hashes.
use super::WorktreeSignature as Worktree;
use crate::atomic_sibling::AtomicSibling;
use sha2::{Digest, Sha256};
use std::{
    ffi::CString,
    fs::{self, Metadata},
    io::Read,
    os::unix::{ffi::OsStrExt, fs::MetadataExt},
    path::Path,
};

#[derive(Default)]
pub(super) struct WorktreeContent {
    digest: Sha256,
    read_bytes: u64,
}

impl WorktreeContent {
    pub(super) fn frame(&mut self, label: &[u8], value: &[u8]) {
        Worktree::hash(&mut self.digest, label, value);
    }

    pub(super) fn added(
        &mut self,
        path: &Path,
        relative: &[u8],
        metadata: &Metadata,
        max_bytes: u64,
    ) -> Option<()> {
        self.frame(b"added-path", relative);
        self.frame(
            b"added-mode",
            (metadata.mode() & 0o7777).to_string().as_bytes(),
        );
        let available = max_bytes.checked_sub(self.read_bytes)?;
        let identity = Worktree::metadata_key(metadata);
        if metadata.is_symlink() {
            let target = fs::read_link(path).ok()?;
            let bytes = target.as_os_str().as_bytes();
            let size = bytes.len() as u64;
            if size > available
                || Worktree::metadata_key(&fs::symlink_metadata(path).ok()?) != identity
            {
                return None;
            }
            self.read_bytes += size;
            self.frame(b"added-content", bytes);
        } else if metadata.is_file() {
            let dir = AtomicSibling::open_directory(path.parent()?)?;
            let name = CString::new(path.file_name()?.as_bytes()).ok()?;
            let file = AtomicSibling::open_relative(&dir, &name, libc::O_RDONLY)?;
            if Worktree::metadata_key(&file.metadata().ok()?) != identity {
                return None;
            }
            let mut read = file.take(available.checked_add(1)?);
            let mut hash = Sha256::new();
            let size = std::io::copy(&mut read, &mut hash).ok()?;
            if size > available
                || Worktree::metadata_key(&read.get_ref().metadata().ok()?) != identity
            {
                return None;
            }
            self.read_bytes += size;
            self.frame(b"added-content-size", size.to_string().as_bytes());
            self.frame(b"added-content-sha256", &hash.finalize());
        } else {
            self.frame(b"added-content", metadata.mode().to_string().as_bytes());
        }
        Some(())
    }

    pub(super) fn finish(mut self, root: &Path) -> Option<String> {
        let (_, head_status) = Worktree::git(root, &["rev-parse", "--verify", "HEAD"], 4096)?;
        let mut args = vec!["diff"];
        if head_status == 0 {
            args.push("HEAD");
        } else {
            let (name, status) = Worktree::git(root, &["symbolic-ref", "-q", "HEAD"], 4096)?;
            let name = std::str::from_utf8(&name).ok()?.trim();
            if status != 0
                || !name.starts_with("refs/heads/")
                || Worktree::git(root, &["show-ref", "--verify", "--quiet", name], 4096)?.1 != 1
            {
                return None;
            }
        }
        args.extend([
            "--binary",
            "--no-renames",
            "--diff-filter=a",
            "--no-ext-diff",
            "--no-textconv",
        ]);
        let (diff, status) = Worktree::git(root, &args, 16 * 1024 * 1024)?;
        if status != 0 {
            return None;
        }
        self.frame(b"working-tree-size", diff.len().to_string().as_bytes());
        self.frame(b"working-tree-sha256", &Sha256::digest(diff));
        Some(format!("{:x}", self.digest.finalize()))
    }
}
