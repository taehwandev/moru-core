//! Owner: bounded Codex exact-command workdir normalization for read ingress.
//! Allowed: JSON/std read-only paths; forbidden: execution, state writes or
//! project authorization. Uncertain shapes preserve original raw Python replay.
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::{Path, PathBuf},
};

pub(crate) fn cwd(payload: &Value, base: &Path, command: &str) -> Option<PathBuf> {
    let Some(record) = latest(payload)? else {
        return Some(base.to_owned());
    };
    if record.get("type").and_then(Value::as_str) == Some("function_call") {
        let arguments: Value = serde_json::from_str(record.get("arguments")?.as_str()?).ok()?;
        let arguments = arguments.as_object()?;
        let cmd = arguments.get("cmd")?.as_str()?;
        let workdir = arguments.get("workdir").and_then(Value::as_str);
        if workdir.is_some_and(|value| value.contains('\0')) {
            return None;
        }
        return if cmd == command {
            selected(workdir, base)
        } else {
            Some(base.to_owned())
        };
    }
    let code = record.get("input")?.as_str()?;
    // Keep the existing conservative profile; escaped or unbounded JS replays.
    if code.contains('\\')
        || code.contains('\0')
        || code.len() > 16 * 1024
        || code.matches('"').count() > 128
    {
        return None;
    }
    let mut workdirs = BTreeSet::new();
    for chunk in code.split("exec_command(").skip(1) {
        let Some(cmd) = property(chunk, "cmd")? else {
            continue;
        };
        let workdir = property(chunk, "workdir")?;
        if cmd == command {
            workdirs.insert(workdir);
        }
    }
    if workdirs.len() != 1 {
        return Some(base.to_owned());
    }
    let workdir = workdirs.first().copied()?;
    selected(workdir, base)
}

fn selected(workdir: Option<&str>, base: &Path) -> Option<PathBuf> {
    let Some(workdir) = workdir.filter(|value| !value.is_empty()) else {
        return Some(base.to_owned());
    };
    if workdir.contains('\0') {
        return None;
    }
    let path = Path::new(workdir);
    if !path.is_absolute() {
        return Some(base.to_owned());
    }
    // A false/exceptional stat is left to Python's original diagnostic behavior.
    path.is_dir().then(|| path.to_owned())
}

fn latest(payload: &Value) -> Option<Option<Value>> {
    let Some(path) = payload.get("transcript_path").and_then(Value::as_str) else {
        return Some(None);
    };
    if path.contains('\0') {
        return None;
    }
    let Ok(mut file) = File::open(path) else {
        return Some(None);
    };
    let Ok(size) = file.seek(SeekFrom::End(0)) else {
        return Some(None);
    };
    if file
        .seek(SeekFrom::Start(size.saturating_sub(512 * 1024)))
        .is_err()
    {
        return Some(None);
    }
    let mut raw = Vec::new();
    if file.take(512 * 1024 + 1).read_to_end(&mut raw).is_err() {
        return Some(None);
    }
    if raw.len() > 512 * 1024
        || String::from_utf8_lossy(&raw).chars().any(|c| {
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
        return None;
    }
    for line in raw.rsplit(|byte| *byte == b'\n') {
        if ![
            b"\"custom_tool_call\"".as_slice(),
            b"\"function_call\"".as_slice(),
        ]
        .iter()
        .any(|kind| line.windows(kind.len()).any(|window| window == *kind))
        {
            continue;
        }
        // A cut multibyte prefix in an older line is harmless. Invalid bytes in
        // the selected record retain Python replacement/coercion via replay.
        let row: Value = serde_json::from_str(std::str::from_utf8(line).ok()?).ok()?;
        let row = row.as_object()?;
        return Some(
            row.get("payload")
                .filter(|value| value.is_object())
                .cloned(),
        );
    }
    Some(None)
}

// Match the legacy first cmd/workdir regex in each exec_command chunk. This
// deliberately does not evaluate JS or invent object/comment scoping rules.
fn property<'a>(text: &'a str, key: &str) -> Option<Option<&'a str>> {
    for (index, _) in text.match_indices(key) {
        let before = text[..index].chars().next_back();
        let mut rest = &text[index + key.len()..];
        let quoted = before == Some('"') && rest.starts_with('"');
        if quoted {
            rest = &rest[1..];
        } else if let Some(c) = before {
            // Python's Unicode word boundary is not inferred from Rust tables.
            if !c.is_ascii() {
                return None;
            }
            if c.is_ascii_alphanumeric() || c == '_' {
                continue;
            }
        }
        rest = rest.trim_start_matches(space);
        let Some(after) = rest.strip_prefix(':') else {
            continue;
        };
        let Some(value) = after.trim_start_matches(space).strip_prefix('"') else {
            continue;
        };
        let Some(end) = value.find('"') else {
            continue;
        };
        // Legacy _decode uses strict JSON strings even for JS input. Raw
        // controls must replay, not select a directory or a later property.
        if value[..end].chars().any(|c| c < '\u{20}') {
            return None;
        }
        return Some(Some(&value[..end]));
    }
    Some(None)
}

fn space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn first_properties_match_quoted_unquoted_and_legacy_comment_shapes() {
        assert_eq!(
            property("{cmd: \"cat a\",workdir:\"/work\"}", "cmd"),
            Some(Some("cat a"))
        );
        assert_eq!(
            property("{\"workdir\":\"/한글\"}", "workdir"),
            Some(Some("/한글"))
        );
        assert_eq!(
            property("notcmd:\"wrong\", cmd:\"right\", cmd:\"later\"", "cmd"),
            Some(Some("right"))
        );
        assert_eq!(
            property("// cmd:\"comment first\"\ncmd:\"later\"", "cmd"),
            Some(Some("comment first"))
        );
    }
    #[test]
    fn uncertain_unicode_boundaries_defer_and_python_whitespace_matches() {
        assert_eq!(property("한cmd:\"x\"", "cmd"), None);
        assert_eq!(property("cmd\u{1c}:\u{85}\"x\"", "cmd"), Some(Some("x")));
        assert_eq!(property("cmd:'single quoted'", "cmd"), Some(None));
        assert_eq!(property("cmd:\"git\tstatus\"", "cmd"), None);
    }
}
