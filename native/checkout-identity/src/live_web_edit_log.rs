//! owner: append one live-web edit record to the project log.
//! allowed imports: anchored filesystem operations and Python JSON formatting.
//! forbidden imports: path claim ownership, lifecycle decisions or network.
//! callers/tests: path_claims record CLI and hook; test_path_claims.
//! verification: byte parity, append integrity and no fallback after a write attempt.
use crate::{
    atomic_sibling::AtomicSibling,
    overhead_clock::OverheadClock,
    python_json::{Object, PythonJson, Value},
};
use serde_json::{json, Value as Json};
use std::{
    io::{self, Write},
    path::Path,
};

pub(super) struct LiveWebEditLog;

impl LiveWebEditLog {
    // None is safe to replay because no append has been attempted.
    pub(super) fn append(input: &Json) -> Option<io::Result<Json>> {
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
        let provided = entry.get("time");
        let time = match provided {
            Some(value) => value.as_str()?.into(),
            None => OverheadClock::utc_now_seconds()?,
        };
        record.insert("time".into(), Value::String(time));
        let mut line = PythonJson::render(&Value::Object(record), false, true)?;
        // The ASCII line can at most double in size when quoted in the receipt.
        if provided.is_none() && line.len() > 512 * 1024 - 64 {
            return None;
        }
        line.push('\n');

        let root = AtomicSibling::open_directory(project)?;
        let local = AtomicSibling::ensure_directory(&root, c".moru")?;
        let web = AtomicSibling::ensure_directory(&local, c"live-web")?;
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
        Some(log.write(line.as_bytes()).and_then(|size| {
            if size != line.len() {
                return Err(io::ErrorKind::WriteZero.into());
            }
            line.pop();
            Ok(if provided.is_some() {
                json!({"appended": true})
            } else {
                json!({"appended": true, "line": line})
            })
        }))
    }
}
