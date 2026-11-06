//! owner: EventTally; allowed imports: parent checked counters and pure text helpers;
//! forbidden imports: raw transcript emission, IO; callers/tests: OverheadHooks;
//! verification: context/plain-output injection, note normalization and stop latency.
use super::*;
pub(super) struct EventTally;
impl EventTally {
    pub(super) fn attachment(entry: &Value, row: &mut Json, shared: &mut Json) -> Option<()> {
        if !entry.is_object() {
            return None;
        }
        let kind = entry["type"].as_str();
        if kind == Some("hook_additional_context") {
            let text = Text::text(&entry["content"]);
            if Text::mark(&text)? || text.contains("continuation guidance") {
                injected(row, &text)?;
            }
            let items = entry["content"]
                .as_array()
                .map(|items| items.iter().map(Py::string).collect::<Vec<_>>())
                .unwrap_or_else(|| vec![text]);
            for item in items {
                if Text::note(&item.chars().take(200).collect::<String>()) {
                    increment(row, "policy_notes", 1)?;
                    map_increment(shared, "notes", &Text::normalize(&item)?)?;
                }
            }
            return Some(());
        }
        if !matches!(
            kind,
            Some("hook_success" | "hook_blocking_error" | "hook_non_blocking_error")
        ) {
            return Some(());
        }
        let command = string_or(&entry["command"], "");
        if !Text::launcher_mark(&command) {
            return Some(());
        }
        let key = format!(
            "{}:{}",
            string_or(&entry["hookEvent"], "?"),
            Text::launcher(&command, false)?.unwrap_or_else(|| "?".into())
        );
        latency(shared, &key, &entry["durationMs"])?;
        let output = if Py::truthy(&entry["stdout"]) {
            Py::string(&entry["stdout"])
        } else {
            string_or(&entry["content"], "")
        };
        let stripped = output.trim_start_matches(crate::python_text::PythonText::whitespace);
        if !stripped.is_empty() && !stripped.starts_with('{') {
            injected(row, &output)?;
        }
        if kind == Some("hook_blocking_error") {
            let error = if Py::truthy(&entry["blockingError"]) {
                Py::string(&entry["blockingError"])
            } else {
                string_or(&entry["stderr"], "")
            };
            increment(
                row,
                "moru_injected_chars",
                i64::try_from(error.chars().count()).ok()?,
            )?;
        }
        Some(())
    }

    pub(super) fn stop(entry: &Value, row: &mut Json, shared: &mut Json) -> Option<()> {
        let infos = &entry["hookInfos"];
        if Py::truthy(infos) && matches!(infos, Value::Bool(_) | Value::Number(_)) {
            return None;
        }
        if let Some(infos) = infos.as_array() {
            for info in infos {
                if !info.is_object() {
                    continue;
                }
                let command = Py::string(&info["command"]);
                if Text::launcher_mark(&command) {
                    let key = format!(
                        "Stop:{}",
                        Text::launcher(&command, false)?.unwrap_or_else(|| "?".into())
                    );
                    latency(shared, &key, &info["durationMs"])?;
                }
            }
        }
        if Py::truthy(&entry["preventedContinuation"]) {
            increment(row, "stop_hook_blocks", 1)?;
        }
        Some(())
    }
}
