//! Owner: read-only empty-inbox proof and acknowledgement counts.
//! Allowed: std, existing safe-path and filesystem readers.
//! Forbidden: packet validation/consumption, receipts, locks, writes or caches.
//! Callers/tests: mailbox_status_process; native mailbox-status and bundle tests.
use crate::{callback_state::LocalState as State, discovery_fs::DiscoveryFs as Fs};
use std::{fs, path::Path};

pub(crate) struct MailboxStatusState;

impl MailboxStatusState {
    pub(crate) fn legacy(project: &Path, runtime: &str) -> Option<usize> {
        let root = project.join(".moru/agent-mailbox");
        State::safe_path(project, &root)?;
        if !Fs::exists(&root)? {
            return Some(0);
        }
        let runs = root.join("runs");
        State::safe_path(project, &runs)?;
        if !Fs::exists(&runs)? {
            return Some(0);
        }
        let mut directories = Vec::new();
        for entry in fs::read_dir(runs).ok()? {
            let path = entry.ok()?.path();
            State::safe_path(project, &path)?;
            let name = path.file_name()?.to_str()?;
            if !path.is_dir()
                || name.len() != 32
                || !name
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return None;
            }
            directories.push(path);
            if directories.len() > 64 {
                return None;
            }
        }
        let mut acked = 0;
        for run in directories {
            if Self::json_count(project, &run.join("inbox").join(runtime))? != 0 {
                return None; // Canonical Python owns every packet and its errors.
            }
            acked += Self::json_count(project, &run.join("acked").join(runtime))?;
            if acked > 128 {
                return None;
            }
        }
        Some(acked)
    }

    pub(crate) fn reference(state: &Path, repository: &str, runtime: &str) -> Option<usize> {
        let root = state.join("agent-mailbox").join(repository);
        State::safe_path(state, &root)?;
        if Self::json_count(state, &root.join("inbox").join(runtime))? != 0 {
            return None;
        }
        Self::json_count(state, &root.join("acked").join(runtime))
    }

    fn json_count(base: &Path, directory: &Path) -> Option<usize> {
        State::safe_path(base, directory)?;
        if !Fs::exists(directory)? {
            return Some(0);
        }
        let mut count = 0;
        for entry in fs::read_dir(directory).ok()? {
            let entry = entry.ok()?;
            // Python counts suffix-matching entries, including directories;
            // acknowledgement payloads are not parsed or validated by status.
            if entry.path().extension().is_some_and(|ext| ext == "json") {
                if entry.file_type().ok()?.is_symlink() {
                    return None;
                }
                count += 1;
                if count > 128 {
                    return None;
                }
            }
        }
        Some(count)
    }
}
