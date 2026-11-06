//! owner: OverheadHooks; allowed imports: pure JSON/text/float helpers and private event tally;
//! forbidden imports: IO, emitting raw commands/prompts; callers/tests: OverheadSession;
//! verification: checked counters, denial redaction, launcher and guidance classification.
#[path = "overhead_hooks_events.rs"]
mod events;
use crate::{
    overhead_text::OverheadText as Text,
    python_float::PythonFloat,
    python_json::{PythonJson as Py, Value},
};
use serde_json::Value as Json;

pub(crate) struct OverheadHooks;
impl OverheadHooks {
    pub(crate) fn attachment(entry: &Value, row: &mut Json, shared: &mut Json) -> Option<()> {
        events::EventTally::attachment(entry, row, shared)
    }
    pub(crate) fn stop(entry: &Value, row: &mut Json, shared: &mut Json) -> Option<()> {
        events::EventTally::stop(entry, row, shared)
    }
    pub(crate) fn user(entry: &Value, row: &mut Json, shared: &mut Json) -> Option<()> {
        let message = &entry["message"];
        if Py::truthy(message) && !message.is_object() {
            return None;
        }
        let content = &message["content"];
        if content.as_str().is_some() && !Py::truthy(&entry["isMeta"]) {
            increment(row, "user_prompts", 1)?;
        }
        let Some(items) = content.as_array() else {
            return Some(());
        };
        let decision = &entry["permissionDecision"];
        for item in items {
            if !item.is_object() || item["type"].as_str() != Some("tool_result") {
                continue;
            }
            let text = Text::text(&item["content"]);
            let prefix: String = text.chars().take(80).collect();
            let hook = decision["source"].as_str() == Some("hook")
                || (text.starts_with("PreToolUse:") && prefix.contains("hook error"));
            if !hook || !(Py::truthy(&entry["toolDenialKind"]) || Py::truthy(&item["is_error"])) {
                continue;
            }
            increment(row, "hook_denials", 1)?;
            if Text::mark(&text.chars().take(400).collect::<String>())? {
                increment(row, "moru_hook_denials", 1)?;
                injected(row, &text)?;
            }
            map_increment(shared, "denials", &Text::normalize(Text::denial(&text)?)?)?;
        }
        Some(())
    }
    pub(crate) fn tool(name: &str, input: &Value, roots: &[String], row: &mut Json) -> Option<()> {
        increment(row, "tool_calls", 1)?;
        map_increment(row, "tools", name)?;
        if matches!(name, "Read" | "Bash") && !input.is_object() {
            return None;
        }
        if name == "Read" && Text::guidance(&input["file_path"], roots) {
            increment(row, "guidance_reads", 1)?;
        }
        if name != "Bash" {
            return Some(());
        }
        let command = string_or(&input["command"], "");
        if let Some(sub) = Text::launcher(&command, true)? {
            if !Text::search(&command)? {
                map_increment(row, "lifecycle_calls", &sub)?;
                increment(row, "lifecycle_total", 1)?;
            }
        }
        if Text::bash_guidance(&command)? {
            increment(row, "guidance_bash_reads", 1)?;
        }
        Some(())
    }
}

fn increment(row: &mut Json, key: &str, amount: i64) -> Option<()> {
    let value = row.get(key)?.as_i64()?.checked_add(amount)?;
    row.as_object_mut()?.insert(key.into(), value.into());
    Some(())
}
fn map_increment(shared: &mut Json, map: &str, key: &str) -> Option<()> {
    let map = shared.get_mut(map)?.as_object_mut()?;
    let count = map
        .get(key)
        .map(Json::as_i64)
        .unwrap_or(Some(0))?
        .checked_add(1)?;
    map.insert(key.into(), count.into());
    Some(())
}
fn injected(row: &mut Json, text: &str) -> Option<()> {
    increment(
        row,
        "moru_injected_chars",
        i64::try_from(text.chars().count()).ok()?,
    )?;
    increment(row, "moru_injected_events", 1)
}
fn string_or(value: &Value, fallback: &str) -> String {
    if Py::truthy(value) {
        Py::string(value)
    } else {
        fallback.into()
    }
}
fn latency(shared: &mut Json, key: &str, value: &Value) -> Option<()> {
    // Python resolves defaultdict[key].append before evaluating float(value).
    let values = shared
        .get_mut("hook_latency")?
        .as_object_mut()?
        .entry(key.to_owned())
        .or_insert_with(|| Json::Array(Vec::new()))
        .as_array_mut()?;
    let number = match value {
        Value::Number(number) => Some(number.as_float()?),
        Value::Bool(value) => Some(if *value { 1.0 } else { 0.0 }),
        Value::String(value) => PythonFloat::parse(value),
        _ => None,
    };
    let Some(number) = number else {
        return Some(());
    };
    let number = serde_json::Number::from_f64(number)?;
    values.push(Json::Number(number));
    Some(())
}

#[cfg(test)]
#[path = "overhead_hooks_tests.rs"]
mod tests;
