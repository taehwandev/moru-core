//! Read-only quiet-state proof under existing Python-compatible locks.
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    env,
    fs::{self, File},
    io::Read,
    os::fd::AsRawFd,
    path::{Path, PathBuf},
};

pub(crate) struct Mailboxes {
    project: PathBuf,
    reference: PathBuf,
    locks: Vec<File>,
}

impl Mailboxes {
    pub(crate) fn quiet(project: &Path, runtime: &str) -> Option<Self> {
        let state = env::var("MORU_STATE_HOME")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .map(|v| PathBuf::from(crate::statusline::Renderer::strip(&v)))
            .unwrap_or(PathBuf::from(env::var_os("HOME")?).join(".moru"));
        if !state.is_absolute() {
            return None;
        }
        let state = state
            .parent()?
            .canonicalize()
            .ok()?
            .join(state.file_name()?);
        let id = moru_checkout_identity::CheckoutIdentity::repository_key(project.to_str()?)?;
        let mut proof = Self {
            project: project.to_owned(),
            reference: state.join("agent-mailbox").join(id),
            locks: Vec::new(),
        };
        safe_path(&state, &proof.reference)?;
        let local = project.join(".moru/agent-mailbox");
        safe_path(project, &local)?;
        for root in [&local, &proof.reference] {
            if absent(root)? {
                continue;
            }
            proof.locks.push(lock(&root.join(".mailbox.lock"))?);
            for category in ["inbox", "leases"] {
                let path = root.join(category).join(runtime);
                safe_path(root, &path)?;
                empty(&path)?;
            }
        }
        Some(proof)
    }

    pub(crate) fn prompt_ready(mut self, core: &Path, runtime: &str, session: &str) -> Option<()> {
        let tasks = self.project.join(".moru/agent-mailbox/task-continuation");
        safe_path(&self.project, &tasks)?;
        if !absent(&tasks)? {
            self.locks.push(lock(&tasks.join(".tasks.lock"))?);
            // Any record or budget can have prompt-boundary effects: replay it.
            for entry in fs::read_dir(&tasks).ok()? {
                let entry = entry.ok()?;
                if entry.file_name() != ".tasks.lock" {
                    return None;
                }
            }
        }
        let source = read(
            &core.join("common/skills/agent-operating-skill/SKILL.md"),
            32768,
        )?;
        let text = source
            .split_once("## Live Session Continuity\n")?
            .1
            .split("\n## ")
            .next()?;
        let text = crate::statusline::Renderer::strip(text);
        if text.is_empty() || text.chars().count() > 4000 {
            return None;
        }
        let identity = format!(
            "{:x}",
            Sha256::digest(format!("{runtime}:{session}").as_bytes())
        );
        let path = self
            .reference
            .join("guidance")
            .join(format!("{identity}.json"));
        safe_path(&self.reference, &path)?;
        let seen: Value = serde_json::from_str(&read(&path, 4096)?).ok()?;
        let digest = format!("{:x}", Sha256::digest(text.as_bytes()));
        (seen.is_object() && seen.get("sha256")?.as_str()? == digest).then_some(())
    }
}

// Reject errors, symlinks and special state; Python owns their diagnostics/effects.
fn absent(path: &Path) -> Option<bool> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.is_dir() => Some(false),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Some(true),
        _ => None,
    }
}

fn safe_path(base: &Path, path: &Path) -> Option<()> {
    let mut current = base.to_owned();
    for part in std::iter::once(None).chain(path.strip_prefix(base).ok()?.components().map(Some)) {
        if let Some(part) = part {
            current.push(part);
        }
        match fs::symlink_metadata(&current) {
            Ok(meta) if !meta.file_type().is_symlink() => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            _ => return None,
        }
    }
    Some(())
}

fn empty(path: &Path) -> Option<()> {
    if absent(path)? {
        return Some(());
    }
    fs::read_dir(path).ok()?.next().is_none().then_some(())
}

fn lock(path: &Path) -> Option<File> {
    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .ok()?;
    if !file.metadata().ok()?.is_file() {
        return None;
    }
    // Closing the descriptor also releases flock, including every fallback path.
    (unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0).then_some(file)
}

fn read(path: &Path, limit: u64) -> Option<String> {
    use std::os::unix::fs::OpenOptionsExt;
    let file = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .ok()?;
    if !file.metadata().ok()?.is_file() {
        return None;
    }
    let mut bytes = String::new();
    file.take(limit + 1).read_to_string(&mut bytes).ok()?;
    (bytes.len() as u64 <= limit).then_some(bytes)
}

use std::os::unix::fs::OpenOptionsExt;
