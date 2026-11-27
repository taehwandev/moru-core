//! Owner: compact UTF-8 HQ report encoding and field truncation.
//! Allowed: ordered JSON and Python whitespace classification.
//! Forbidden: files, clocks, environment, and report publication.
//! Callers/tests: completion probe and HQ finish and decision report tests.
use crate::python_text::PythonText;
use serde_json::{json, Map, Value};

const PRIMARY: [&str; 3] = ["evidence", "result", "decisionNeeded"];
const FALLBACK: [&str; 3] = ["operatorLabel", "taskId", "projectId"];

fn supported(value: &Value) -> bool {
    match value {
        Value::String(_) | Value::Null | Value::Bool(_) => true,
        Value::Number(number) => number.is_i64() || number.is_u64(),
        Value::Array(values) => values.iter().all(Value::is_string),
        Value::Object(_) => false,
    }
}

// Python max() prefers the first field with the longest Unicode string.
fn longest<'a>(
    fields: &'a Map<String, Value>,
    candidates: &[&'static str],
) -> Option<(&'static str, &'a str, usize)> {
    let mut selected = None;
    let mut longest = 0;
    for &key in candidates {
        if let Some(text) = fields.get(key).and_then(Value::as_str) {
            let length = text.chars().count();
            if length > longest {
                longest = length;
                selected = Some((key, text, length));
            }
        }
    }
    selected
}

pub(super) fn encode(request: &Value) -> Option<Value> {
    let max_bytes = usize::try_from(request.get("max_bytes")?.as_u64()?).ok()?;
    let mut fields = request.get("payload")?.as_object()?.clone();
    if !fields.values().all(supported)
        || PRIMARY
            .iter()
            .chain(&FALLBACK)
            .any(|key| fields.get(*key).is_some_and(|v| !v.is_string()))
    {
        return None;
    }

    // preserve_order keeps the order of the Python caller's original dict.
    let mut encoded = serde_json::to_string(&fields).ok()?;
    while encoded.len() > max_bytes {
        let Some((key, text, chars)) =
            longest(&fields, &PRIMARY).or_else(|| longest(&fields, &FALLBACK))
        else {
            break;
        };
        let overflow = encoded.len() - max_bytes;
        let drop = if overflow > 6 { overflow / 3 } else { 1 };
        let target = chars.saturating_sub(drop);
        let replacement = if target >= 4 {
            let prefix: String = text.chars().take(target - 3).collect();
            format!("{}...", prefix.trim_end_matches(PythonText::whitespace))
        } else {
            text.chars().take(target).collect()
        };
        fields.insert(key.into(), Value::String(replacement));
        encoded = serde_json::to_string(&fields).ok()?;
    }
    Some(json!({"encoded": encoded}))
}
