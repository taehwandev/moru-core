use serde_json::{Map, Value};

/// Python semantics shared by the statusline modules.
pub(crate) struct Py;

impl Py {
    pub(crate) fn strip(text: &str) -> &str {
        text.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
    }

    pub(crate) fn truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(flag) => *flag,
            Value::Number(number) => number.as_f64().is_none_or(|f| f != 0.0),
            Value::String(text) => !text.is_empty(),
            Value::Array(items) => !items.is_empty(),
            Value::Object(map) => !map.is_empty(),
        }
    }

    /// Python `a.get(k1) or a.get(k2) or ...`: first truthy value, else None.
    pub(crate) fn pick<'a>(object: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
        keys.iter()
            .filter_map(|key| object.get(*key))
            .find(|value| Self::truthy(value))
    }
}
