//! Validate Codex normalization's failure boundary; never retain transcript data.
//! Plain-query verdicts are cwd-independent; uncertain shapes replay in Python.
use serde_json::Value;
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

pub(crate) fn safe(payload: &Value) -> bool {
    let Some(path) = payload.get("transcript_path").and_then(Value::as_str) else {
        return true;
    };
    if path.contains('\0') {
        return false;
    }
    let Ok(mut file) = File::open(path) else {
        return true;
    };
    let Ok(size) = file.seek(SeekFrom::End(0)) else {
        return true;
    };
    if file
        .seek(SeekFrom::Start(size.saturating_sub(512 * 1024)))
        .is_err()
    {
        return true;
    }
    let mut raw = Vec::new();
    if file.take(512 * 1024 + 1).read_to_end(&mut raw).is_err() {
        return true;
    }
    let text = String::from_utf8_lossy(&raw);
    if raw.len() > 512 * 1024
        || text.chars().any(|c| {
            matches!(
                c,
                '\r' | '\u{b}'
                    | '\u{c}'
                    | '\u{1c}'
                    | '\u{1d}'
                    | '\u{1e}'
                    | '\u{85}'
                    | '\u{2028}'
                    | '\u{2029}'
            )
        })
    {
        return false;
    }
    for line in text.lines().rev() {
        if !line.contains("\"custom_tool_call\"") && !line.contains("\"function_call\"") {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            return false;
        };
        let Some(row) = row.as_object() else {
            return false;
        };
        let Some(record) = row.get("payload").and_then(Value::as_object) else {
            return true;
        };
        if record.get("type").and_then(Value::as_str) == Some("function_call") {
            let Some(arguments) = record.get("arguments").and_then(Value::as_str) else {
                return false;
            };
            let Ok(arguments) = serde_json::from_str::<Value>(arguments) else {
                return false;
            };
            return arguments
                .get("workdir")
                .and_then(Value::as_str)
                .is_none_or(|path| {
                    !path.contains('\0')
                        && (!Path::new(path).is_absolute() || Path::new(path).is_dir())
                });
        }
        let Some(code) = record.get("input").and_then(Value::as_str) else {
            return false;
        };
        // Without escapes, every string the legacy regex can extract is valid
        // UTF-8 and cannot decode to a NUL or lone surrogate in a workdir.
        return !code.contains('\\') && !code.contains('\0');
    }
    true
}
