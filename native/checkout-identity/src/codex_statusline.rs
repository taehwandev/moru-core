//! owner: CodexStatusLine text merge and setup dispatch; allowed: JSON and bounded setup;
//! forbidden imports: direct config I/O, Python and providers;
//! callers/tests: guarded setup probes and synthetic setup parity tests;
//! verification: exact text oracle, no-helper-replay and empty-PATH protocol.
#[path = "codex_statusline_render.rs"]
mod render;
#[path = "codex_statusline_setup.rs"]
mod setup;
#[path = "codex_statusline_syntax.rs"]
mod syntax;
use crate::pretool_guard::CallbackGuard;
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
};

pub(crate) struct CodexStatusLine;
impl CodexStatusLine {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(operation) = args.get(1).and_then(|arg| arg.to_str()) else {
            return 125;
        };
        if args.len() != 2
            || !matches!(
                operation,
                "codex-status-line" | "codex-status-line-plan" | "codex-status-line-apply"
            )
            || CallbackGuard::root(launcher, "setup-probe").is_none()
        {
            return 125;
        }
        let mut input = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut input)
            .is_err()
            || input.len() > 1024 * 1024
        {
            return 125;
        }
        let Some(payload) = serde_json::from_slice::<Value>(&input).ok() else {
            return 125;
        };
        let Some(object) = payload.as_object() else {
            return 125;
        };
        let result = if operation == "codex-status-line" {
            let Some(text) = object
                .get("text")
                .and_then(Value::as_str)
                .filter(|_| object.len() == 1)
            else {
                return 125;
            };
            let (status, text) = Self::merge(text);
            json!({"status":status, "text":text})
        } else {
            if !object.is_empty() {
                return 125;
            }
            match Self::configure_default(operation == "codex-status-line-plan") {
                Some(Ok(status)) => json!({"status":status}),
                Some(Err(error)) => {
                    eprintln!("Codex quota status line: {error}");
                    return 1;
                }
                None => return 125,
            }
        };
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1, "result":result}))
        else {
            return 125;
        };
        output.push(b'\n');
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }

    fn merge(text: &str) -> (&'static str, String) {
        let headers = Self::headers(text);
        let tui: Vec<_> = headers
            .iter()
            .filter(|(_, _, name)| Self::strip(name) == "tui")
            .collect();
        if tui.len() > 1 {
            return ("missing", text.into());
        }
        let (start, end, key) = if let Some((start, end, _)) = tui.first().copied() {
            (
                *end,
                headers
                    .iter()
                    .find(|(next, _, _)| next > start)
                    .map_or(text.len(), |h| h.0),
                "status_line",
            )
        } else {
            (
                0,
                headers.first().map_or(text.len(), |h| h.0),
                "tui.status_line",
            )
        };
        let assignments = Self::assignments(&text[start..end], key);
        if assignments.len() > 1 {
            return ("missing", text.into());
        }
        let updated = if let Some(equals_end) = assignments.first() {
            let opening = start + equals_end;
            let opening = opening + text[opening..].len()
                - text[opening..].trim_start_matches(Self::space).len();
            if text.as_bytes().get(opening) != Some(&b'[') {
                return ("missing", text.into());
            }
            let Some(closing) = Self::array_end(text, opening) else {
                return ("missing", text.into());
            };
            let Some(items) = Self::items(&text[opening + 1..closing]) else {
                return ("missing", text.into());
            };
            let missing: Vec<_> = ["five-hour-limit", "weekly-limit"]
                .into_iter()
                .filter(|item| !items.iter().any(|existing| existing == item))
                .collect();
            if missing.is_empty() {
                return ("ok", text.into());
            }
            Self::append(text, opening, closing, &missing)
        } else {
            let Some(updated) = Self::insert(text, &headers) else {
                return ("missing", text.into());
            };
            updated
        };
        (if updated == text { "ok" } else { "changed" }, updated)
    }

    fn space(c: char) -> bool {
        c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
    }
    fn strip(text: &str) -> &str {
        text.trim_matches(Self::space)
    }
}

#[cfg(test)]
#[path = "codex_statusline_tests.rs"]
mod tests;
