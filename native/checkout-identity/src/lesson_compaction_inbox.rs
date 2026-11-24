//! owner: bounded read-only lesson compaction inbox discovery and grouping.
//! allowed imports: local bounded reads and Python-compatible JSON.
//! forbidden imports: locks, compaction writes and authority decisions.
//! callers/tests: lessons-compact read_records and test_lessons_compact.
//! verification: filename order, payload lesson IDs, unreadable records and decline.
use crate::{
    callback_state::LocalState,
    python_json::{InputDiagnostic, PythonJson},
};
use serde_json::{json, Value};
use std::{collections::HashMap, fs, path::Path};

pub(super) struct LessonCompactionInbox;

impl LessonCompactionInbox {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let inbox = Path::new(input.get("inbox")?.as_str()?);
        if !inbox.is_absolute() || inbox.canonicalize().ok()? != inbox {
            return None;
        }
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let mut names = Vec::new();
        for (index, entry) in fs::read_dir(inbox).ok()?.enumerate() {
            if index == 4096 {
                return None;
            }
            let name = entry.ok()?.file_name().into_string().ok()?;
            if name.ends_with(".json") {
                names.push(name);
            }
        }
        names.sort_unstable();

        let mut group_index = HashMap::new();
        let mut groups: Vec<(String, Vec<(String, String)>)> = Vec::new();
        let mut unreadable = Vec::new();
        let mut bytes = 0;
        for name in names {
            let raw = LocalState::read(&inbox.join(&name), 64 * 1024)?;
            bytes += raw.len();
            if bytes > 768 * 1024 {
                return None;
            }
            let lesson = match PythonJson::parse_with_diagnostic(&raw, Some(limit), None) {
                Ok(Some(record)) if record.is_object() => record
                    .get("lesson_id")
                    .filter(|value| PythonJson::truthy(value))
                    .map(PythonJson::string),
                Ok(Some(_)) | Err(InputDiagnostic::Syntax(_)) => None,
                _ => return None,
            };
            if let Some(lesson) = lesson {
                let index = *group_index.entry(lesson.clone()).or_insert_with(|| {
                    groups.push((lesson, Vec::new()));
                    groups.len() - 1
                });
                groups[index].1.push((name, raw));
            } else {
                unreadable.push(name);
            }
        }
        let receipt = json!({"groups": groups, "unreadable": unreadable});
        (serde_json::to_vec(&receipt).ok()?.len() < 1024 * 1024 - 128).then_some(receipt)
    }
}
