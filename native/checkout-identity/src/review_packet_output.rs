//! owner: exclusive creation of the explicit local review-packet output.
//! allowed imports: guarded directory descriptors, bounded JSON, and file writes.
//! forbidden imports: removal, replacement, parent creation, Git and provider calls.
//! callers/tests: review packet probe and the ordinary CLI output fixtures.
//! verification: exact bytes and umask, existing targets, and no replay after attempts.
use crate::atomic_sibling::AtomicSibling;
use serde_json::{json, Value};
use std::{ffi::CString, io::Write, os::fd::IntoRawFd, path::Path};

pub(crate) struct ReviewPacketOutput;
impl ReviewPacketOutput {
    pub(crate) fn create(request: &Value) -> Option<Value> {
        let path = request.get("path")?.as_str()?;
        let text = request.get("text")?.as_str()?;
        if !path.starts_with('/')
            || path.len() >= libc::PATH_MAX as usize
            || !text.starts_with("{\n")
            || !text.ends_with("}\n")
        {
            return None;
        }
        let packet: Value = serde_json::from_str(text).ok()?;
        if packet["kind"] != "review_packet"
            || packet["schema_version"] != 1
            || packet["context_only"] != true
            || packet["no_execution"] != true
            || text.len() as u64 > packet["max_bytes"].as_u64()?
        {
            return None;
        }
        let (parent, name) = path.rsplit_once('/')?;
        if matches!(name, "" | "." | "..") || name.len() > 255 {
            return None;
        }
        let name = CString::new(name).ok()?;
        let directory =
            AtomicSibling::open_directory(Path::new(if parent.is_empty() { "/" } else { parent }))?;
        let flags = libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL;
        let Ok(mut file) = AtomicSibling::open_relative_with_mode(&directory, &name, flags, 0o666)
        else {
            return Some(json!({"written": false}));
        };
        let wrote = file.write_all(text.as_bytes()).is_ok();
        let closed = unsafe { libc::close(file.into_raw_fd()) } == 0;
        Some(json!({"written": wrote && closed}))
    }
}
