//! owner: OverheadSession; allowed imports: JSON, timestamp/number helpers, OverheadHooks;
//! forbidden imports: file/process/network I/O; callers/tests: overhead native adapter;
//! verification: per-session rows, deduplication, windows and whole-call decline parity.
#[path = "overhead_session_number.rs"]
mod number;
use crate::overhead_stamp::OverheadStamp;
use crate::{
    overhead_hooks::OverheadHooks,
    python_json::{Object, ParseOutcome, PythonJson, Value},
};
use number::SessionNumber;
use serde_json::{json, Value as Json};
use std::{cmp::Ordering, collections::HashSet};
pub(crate) struct OverheadSession;
struct Tally<'a> {
    roots: &'a [String],
    row: Json,
    shared: Json,
    messages: HashSet<String>,
    tools: HashSet<String>,
    first: Option<OverheadStamp>,
    last: Option<OverheadStamp>,
    since: Option<OverheadStamp>,
    until: Option<OverheadStamp>,
}
impl OverheadSession {
    pub(crate) fn measure(
        path: &str,
        text: &str,
        roots: &[String],
        window: &[Json],
    ) -> Option<Json> {
        if window.len() != 2 {
            return None;
        }
        let mut tally = Tally {
            roots,
            row: Self::row(path),
            shared: json!({"notes":{},"denials":{},"hook_latency":{}}),
            messages: HashSet::new(),
            tools: HashSet::new(),
            first: None,
            last: None,
            since: Self::window(&window[0])?,
            until: Self::window(&window[1])?,
        };
        for line in text.split('\n') {
            let entry = match PythonJson::parse_outcome(line) {
                ParseOutcome::Value(value) => value,
                ParseOutcome::Unsupported => return None,
                ParseOutcome::Invalid => {
                    // JSONDecodeError is skipped; digit-conversion ValueError escapes Python.
                    let error = PythonJson::error(line)?;
                    if !error.ends_with(')') || !error.contains(" (char ") {
                        return None;
                    }
                    continue;
                }
            };
            if entry.is_object() {
                tally.add(&entry)?;
            }
        }
        let mut total = 0i64;
        for field in [
            "tok_input",
            "tok_cache_read",
            "tok_cache_create",
            "tok_output",
        ] {
            total = total.checked_add(tally.row[field].as_i64()?)?;
        }
        tally.row["tok_total"] = json!(total);
        tally.row["moru_injected_tokens_est"] =
            json!(tally.row["moru_injected_chars"].as_i64()?.div_euclid(4));
        tally.row["moru_core"] = json!(tally.row["cwd"]
            .as_str()
            .is_some_and(|cwd| !cwd.is_empty() && roots.iter().any(|root| cwd.starts_with(root))));
        Some(json!({"row":tally.row,"shared":tally.shared}))
    }
    fn window(value: &Json) -> Option<Option<OverheadStamp>> {
        if value.is_null() {
            return Some(None);
        }
        Some(Some(OverheadStamp::parse(value.as_str()?)??))
    }
    fn row(path: &str) -> Json {
        let basename = |s: &str| s.rsplit('/').next().unwrap_or("").to_owned();
        let parent = path.rsplit_once('/').map_or("", |(p, _)| p);
        let parent = if parent.chars().all(|c| c == '/') {
            parent
        } else {
            parent.trim_end_matches('/')
        };
        let mut row = json!({});
        for name in [
            "assistant_turns",
            "user_prompts",
            "tool_calls",
            "lifecycle_total",
            "policy_notes",
            "hook_denials",
            "moru_hook_denials",
            "stop_hook_blocks",
            "guidance_reads",
            "guidance_bash_reads",
            "tok_input",
            "tok_cache_read",
            "tok_cache_create",
            "tok_output",
            "moru_injected_chars",
            "moru_injected_events",
        ] {
            row[name] = json!(0);
        }
        for (name, value) in [
            ("file", json!(basename(path))),
            ("project_dir", json!(basename(parent))),
            ("cwd", Json::Null),
            ("first_ts", Json::Null),
            ("last_ts", Json::Null),
            ("tools", json!({})),
            ("lifecycle_calls", json!({})),
        ] {
            row[name] = value;
        }
        row
    }
}
impl Tally<'_> {
    fn add(&mut self, entry: &Value) -> Option<()> {
        if self.row["cwd"].as_str().is_none_or(str::is_empty) {
            if let Some(cwd) = entry["cwd"].as_str() {
                self.row["cwd"] = json!(cwd);
            }
        }
        if PythonJson::truthy(&entry["timestamp"]) {
            if let Some(stamp) = OverheadStamp::parse(&PythonJson::string(&entry["timestamp"]))? {
                if let Some(since) = &self.since {
                    if stamp.compare(since)? == Ordering::Less {
                        return Some(());
                    }
                }
                if let Some(until) = &self.until {
                    if stamp.compare(until)? == Ordering::Greater {
                        return Some(());
                    }
                }
                if self.first.as_ref().map_or(Some(true), |first| {
                    stamp.compare(first).map(|o| o == Ordering::Less)
                })? {
                    self.first = Some(stamp.clone());
                }
                if self.last.as_ref().map_or(Some(true), |last| {
                    stamp.compare(last).map(|o| o == Ordering::Greater)
                })? {
                    self.last = Some(stamp);
                }
                self.row["first_ts"] = json!(self.first.as_ref()?.iso);
                self.row["last_ts"] = json!(self.last.as_ref()?.iso);
            }
        }
        match entry["type"].as_str() {
            Some("assistant") => self.assistant(&entry["message"], &entry["uuid"]),
            Some("user") => OverheadHooks::user(entry, &mut self.row, &mut self.shared),
            Some("attachment") => {
                let empty = Value::Object(Object::new());
                let attachment = if PythonJson::truthy(&entry["attachment"]) {
                    &entry["attachment"]
                } else {
                    &empty
                };
                OverheadHooks::attachment(attachment, &mut self.row, &mut self.shared)
            }
            Some("system") if entry["subtype"].as_str() == Some("stop_hook_summary") => {
                OverheadHooks::stop(entry, &mut self.row, &mut self.shared)
            }
            _ => Some(()),
        }
    }
    fn assistant(&mut self, message: &Value, fallback: &Value) -> Option<()> {
        let empty = Value::Object(Object::new());
        let message = if PythonJson::truthy(message) {
            message
        } else {
            &empty
        };
        message.as_object()?;
        let id = if PythonJson::truthy(&message["id"]) {
            &message["id"]
        } else {
            fallback
        };
        if self.messages.insert(SessionNumber::identity(id)?) {
            self.increment("assistant_turns", 1)?;
            let usage = if PythonJson::truthy(&message["usage"]) {
                &message["usage"]
            } else {
                &empty
            };
            usage.as_object()?;
            for (field, counter) in [
                ("input_tokens", "tok_input"),
                ("cache_read_input_tokens", "tok_cache_read"),
                ("cache_creation_input_tokens", "tok_cache_create"),
                ("output_tokens", "tok_output"),
            ] {
                self.increment(counter, SessionNumber::integer(&usage[field])?)?;
            }
        }
        let blocks = match &message["content"] {
            Value::Array(blocks) => blocks.as_slice(),
            Value::String(_) | Value::Object(_) => &[],
            value if !PythonJson::truthy(value) => &[],
            _ => return None,
        };
        for block in blocks {
            if !block.is_object() || block["type"].as_str() != Some("tool_use") {
                continue;
            }
            if !self.tools.insert(SessionNumber::identity(&block["id"])?) {
                continue;
            }
            let name = if PythonJson::truthy(&block["name"]) {
                block["name"].as_str()?
            } else {
                "?"
            };
            let input = if PythonJson::truthy(&block["input"]) {
                &block["input"]
            } else {
                &empty
            };
            OverheadHooks::tool(name, input, self.roots, &mut self.row)?;
        }
        Some(())
    }
    fn increment(&mut self, name: &str, value: i64) -> Option<()> {
        self.row[name] = json!(self.row[name].as_i64()?.checked_add(value)?);
        Some(())
    }
}

#[cfg(test)]
#[path = "overhead_session_tests.rs"]
mod tests;
