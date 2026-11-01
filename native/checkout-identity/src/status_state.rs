//! Prepared status reads with Python's project/file lock order; no creation.
//! Owner: status-state I/O. Allowed: LocalState, serde_json, std/libc.
//! Forbidden: registry/scheduler mutations, lock creation and policy decisions.
//! Callers/tests: StatusProcess; native status parity/contention/transport tests.
//! Verification: existing writable locks, bounded JSON and conservative fallback.
use crate::callback_state::LocalState as State;
use serde_json::Value;
use std::{
    fs::{self, File},
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
    path::Path,
};

pub(crate) struct StatusState;

impl StatusState {
    pub(crate) fn read(project: &Path) -> Option<[Value; 3]> {
        let local = project.join(".moru");
        State::safe_path(project, &local.join(".state.lock"))?;
        let _project_lock = lock(&local.join(".state.lock.lock"))?;
        let read = |name: &str| {
            let path = local.join(name);
            State::safe_path(project, &path)?;
            let _file_lock = lock(&local.join(format!(".{name}.lock")))?;
            match fs::symlink_metadata(&path) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    Some(serde_json::json!({}))
                }
                Ok(meta) if meta.is_file() && !meta.file_type().is_symlink() => {
                    let value: Value =
                        serde_json::from_str(&State::read(&path, 1_048_576)?).ok()?;
                    value.is_object().then_some(value)
                }
                _ => None,
            }
        };
        Some([
            read("run-registry.json")?,
            read("scheduler.json")?,
            read("events.json")?,
        ])
    }
}

fn lock(path: &Path) -> Option<File> {
    // Python opens a+b. Require write permission too, but never create a lock.
    let file = fs::OpenOptions::new()
        .read(true)
        .append(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .ok()?;
    if !file.metadata().ok()?.is_file() {
        return None;
    }
    (unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0).then_some(file)
}
