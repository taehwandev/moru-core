//! Validate Codex normalization's failure boundary; never retain transcript data.
//! Check normalized workdir diagnostics and shadows; uncertain shapes replay in Python.
use serde_json::Value;
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};

pub(crate) fn safe(payload: &Value, file_command: Option<&str>, output: Option<&str>) -> bool {
    let valid_directory = |path: &str| {
        file_command.is_none_or(|command| {
            crate::pretool_files::FileQuery::command(command)
                .is_some_and(|query| query.ready(Path::new(path)))
        }) && output.is_none_or(|program| {
            std::fs::symlink_metadata(Path::new(path).join(program))
                .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
        })
    };
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
                        && (!Path::new(path).is_absolute() || valid_directory(path))
                });
        }
        let Some(code) = record.get("input").and_then(Value::as_str) else {
            return false;
        };
        // Without escapes, every string the legacy regex can extract is valid
        // UTF-8 and cannot decode to a NUL or lone surrogate in a workdir.
        if code.contains('\\') || code.contains('\0') {
            return false;
        }
        // Comments and single-quoted/template strings can change quote parity.
        // Check every fragment, and never discard stat failures: Python may
        // surface them as a normalization diagnostic even for Git/pwd queries.
        if code.len() > 16 * 1024 || code.matches('"').count() > 128 {
            return false;
        }
        return code
            .split('"')
            .filter(|p| Path::new(p).is_absolute())
            .all(|p| Path::new(p).is_dir() && valid_directory(p));
    }
    true
}
