//! owner: CodexStatusLine; allowed imports: std, JSON and CallbackGuard;
//! forbidden imports: config IO/writes, Python, providers and installation;
//! callers/tests: guarded setup probe and synthetic setup parity tests;
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
        if args.len() != 2
            || args[1] != "codex-status-line"
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
        let Some(text) = object
            .get("text")
            .and_then(Value::as_str)
            .filter(|_| object.len() == 1)
        else {
            return 125;
        };
        let (status, updated) = Self::merge(text);
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1,
            "result":{"status":status,"text":updated}}))
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
