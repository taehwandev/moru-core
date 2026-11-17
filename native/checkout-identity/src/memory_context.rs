//! owner: MemoryContext; allowed imports: JSON/std/MemoryRecall;
//! forbidden imports: filesystem, processes, stores, writes, providers, authority;
//! callers/tests: MemoryProcess recall-context; verification: Python output oracles.
use crate::memory_recall::MemoryRecall;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

pub(crate) struct MemoryContext;
const REQUIRED: [&str; 4] = ["id", "body", "source", "review_on"];
const OPTIONAL: [&str; 2] = ["applies_when", "not_when"];

impl MemoryContext {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 6 {
            return None;
        }
        let limits = object.get("limits")?.as_object()?;
        if limits.len() != 3 {
            return None;
        }
        let items = Self::limit(limits.get("items")?, 256)?;
        let budget = Self::limit(limits.get("chars")?, 1_000_000)?;
        let previous = Self::limit(limits.get("previous")?, 1_000_000)?;
        if previous == 0 {
            return None;
        }
        let records = object.get("records")?.as_array()?;
        let mut by_id = HashMap::new();
        for row in records {
            let fields = row.as_object()?;
            for key in REQUIRED.into_iter().chain(["status", "scope"]) {
                fields.get(key)?.as_str()?;
            }
            for key in OPTIONAL {
                if let Some(value) = fields.get(key) {
                    value.as_str()?;
                }
            }
            if let Some(files) = fields.get("source_files") {
                if !files.as_array()?.is_empty() {
                    return None;
                }
            }
            by_id.insert(fields.get("id")?.as_str()?, row);
        }
        let mut recall = payload.clone();
        recall.as_object_mut()?.remove("limits");
        let selected = MemoryRecall::evaluate("recall", &recall)?;
        let mut result = Vec::new();
        let mut used = 0;
        for value in selected.get("indices")?.as_array()? {
            if result.len() >= items {
                break;
            }
            let row = records.get(usize::try_from(value.as_u64()?).ok()?)?;
            let mut fields = Map::new();
            for key in REQUIRED.into_iter().chain(OPTIONAL) {
                if let Some(value) = row.get(key) {
                    fields.insert(key.to_owned(), value.clone());
                }
            }
            let target = row.get("replaces").and_then(Value::as_str).unwrap_or("");
            if let Some(old) = by_id.get(target) {
                let body = old.get("body")?.as_str()?;
                let body = if body.chars().count() > previous {
                    body.chars().take(previous - 1).chain(['…']).collect()
                } else {
                    body.to_owned()
                };
                fields.insert("previously".to_owned(), json!(body));
            }
            let size = Self::python_size(&fields)?;
            if used + size <= budget {
                used += size;
                result.push(Value::Object(fields));
            }
        }
        Some(json!({"items":result}))
    }

    fn limit(value: &Value, max: usize) -> Option<usize> {
        let n = usize::try_from(value.as_u64()?).ok()?;
        (n <= max).then_some(n)
    }

    fn python_size(fields: &Map<String, Value>) -> Option<usize> {
        // Python's default JSON separators are ", " and ": "; only strings
        // enter this profile, so no float/encoder compatibility is assumed.
        let mut text = String::from("{");
        for (index, (key, value)) in fields.iter().enumerate() {
            if index != 0 {
                text.push_str(", ");
            }
            text.push_str(&serde_json::to_string(key).ok()?);
            text.push_str(": ");
            text.push_str(&serde_json::to_string(value.as_str()?).ok()?);
        }
        text.push('}');
        Some(text.chars().count())
    }
}

#[cfg(test)]
#[path = "memory_context_tests.rs"]
mod tests;
