//! owner: append one live-web edit record to the project log.
//! allowed imports: anchored filesystem operations and Python JSON formatting.
//! forbidden imports: path claim ownership, lifecycle decisions or network.
//! callers/tests: path_claims record CLI and hook; test_path_claims.
//! verification: byte parity, append integrity and no fallback after a write attempt.
use crate::{
    atomic_sibling::AtomicSibling,
    python_json::{Object, PythonJson, Value},
};
use serde_json::Value as Json;
use std::{ffi::CStr, fs::File, io::Write, os::fd::AsRawFd, path::Path};

pub(super) struct LiveWebEditLog;

impl LiveWebEditLog {
    // None is safe to replay because no append has been attempted.
    pub(super) fn append(input: &Json) -> Option<bool> {
        let project = Path::new(input.get("project")?.as_str()?);
        let entry = input.get("entry")?;
        let mut record = Object::new();
        record.insert(
            "session".into(),
            Value::String(entry.get("session")?.as_str()?.into()),
        );
        let files = entry
            .get("files")?
            .as_array()?
            .iter()
            .map(|file| Some(Value::String(file.as_str()?.into())))
            .collect::<Option<Vec<_>>>()?;
        record.insert("files".into(), Value::Array(files));
        record.insert(
            "time".into(),
            Value::String(entry.get("time")?.as_str()?.into()),
        );
        let mut line = PythonJson::render(&Value::Object(record), false, true)?;
        line.push('\n');

        let root = AtomicSibling::open_directory(project)?;
        let local = Self::directory(&root, c".moru")?;
        let web = Self::directory(&local, c"live-web")?;
        let mut log = AtomicSibling::open_relative(
            &web,
            c"edits.jsonl",
            libc::O_WRONLY | libc::O_APPEND | libc::O_CREAT,
        )?;
        if !log.metadata().ok()?.is_file() {
            return None;
        }
        // A single append keeps records contiguous with other appenders.
        // A partial write must surface as an error, never as a replay.
        Some(
            log.write(line.as_bytes())
                .is_ok_and(|size| size == line.len()),
        )
    }

    fn directory(parent: &File, name: &CStr) -> Option<File> {
        let flags = libc::O_RDONLY | libc::O_DIRECTORY;
        match AtomicSibling::open_relative_result(parent, name, flags) {
            Ok(dir) => return Some(dir),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return None,
        }
        // Open relative to the stable parent descriptor after mkdir, including
        // when a concurrent creator wins. Never follow a symlink here.
        unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o777 as libc::mode_t) };
        AtomicSibling::open_relative(parent, name, flags)
    }
}
