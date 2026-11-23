//! owner: MemoryContext; allowed imports: JSON, std, MemoryRecall and Unicode profile;
//! forbidden imports: filesystem, processes, stores, writes, providers, authority;
//! callers/tests: live recall and offline evaluation; verification: Python output oracles.
use crate::{memory_recall::MemoryRecall, memory_terms::MemoryTerms};
use serde_json::{json, Map, Value};
use std::collections::HashMap;

pub(crate) struct MemoryContext;
const REQUIRED: [&str; 4] = ["id", "body", "source", "review_on"];
const OPTIONAL: [&str; 2] = ["applies_when", "not_when"];

impl MemoryContext {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 6 || object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let records = object.get("records")?.as_array()?;
        let indices = MemoryRecall::rank(
            object.get("scope")?.as_str()?,
            object.get("today")?.as_str()?,
            object.get("context")?.as_str()?,
            records,
        )?;
        let projected = Self::project(records, &indices, object.get("limits")?)?;
        let items: Vec<_> = projected.into_iter().map(|(fields, _)| fields).collect();
        Some(json!({"items": items}))
    }

    pub(crate) fn project(
        records: &[Value],
        indices: &[usize],
        limits: &Value,
    ) -> Option<Vec<(Value, String)>> {
        let limits = limits.as_object()?;
        if limits.len() != 3 {
            return None;
        }
        let items = Self::limit(limits.get("items")?, 256)?;
        let budget = Self::limit(limits.get("chars")?, 1_000_000)?;
        let previous = Self::limit(limits.get("previous")?, 1_000_000)?;
        if previous == 0 {
            return None;
        }
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
        let mut result = Vec::new();
        let mut used = 0;
        for &index in indices {
            if result.len() >= items {
                break;
            }
            let row = records.get(index)?;
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
            let payload = Self::python_payload(&fields)?;
            let size = payload.chars().count();
            if used + size <= budget {
                used += size;
                result.push((Value::Object(fields), payload));
            }
        }
        Some(result)
    }

    fn limit(value: &Value, max: usize) -> Option<usize> {
        let n = usize::try_from(value.as_u64()?).ok()?;
        (n <= max).then_some(n)
    }

    fn python_payload(fields: &Map<String, Value>) -> Option<String> {
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
        Some(text)
    }
}

#[cfg(test)]
#[path = "memory_context_tests.rs"]
mod tests;
