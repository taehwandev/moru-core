//! Owner: Figma character-style override runs. Allowed imports: ordered JSON, target and text style.
//! Forbidden: filesystem and network. Verification: native text-run parity fixtures.
use super::{target::Target, text_style};
use crate::python_json::{Number, Object, PythonJson, Value};
use serde_json::json;

const LIMIT: usize = 1024 * 1024;

fn numeric(value: &Value) -> Option<f64> {
    match value {
        Value::Bool(value) => Some(u8::from(*value) as f64),
        Value::Number(n) => n
            .as_float()
            .filter(|v| v.is_finite() && v.abs() < 9_007_199_254_740_992.0),
        _ => None,
    }
}

fn same(a: &Value, b: &Value) -> Option<bool> {
    match (a, b) {
        (Value::Number(Number::Integer(a)), Value::Number(Number::Integer(b))) => Some(a == b),
        (Value::Bool(_) | Value::Number(_), Value::Bool(_) | Value::Number(_)) => {
            Some(numeric(a)? == numeric(b)?)
        }
        (Value::Null, Value::Null) => Some(true),
        (Value::String(a), Value::String(b)) => Some(a == b),
        (Value::Array(_) | Value::Object(_), _) | (_, Value::Array(_) | Value::Object(_)) => None,
        _ => Some(false),
    }
}

struct Runs<'a> {
    node: &'a Value,
    text: String,
    boundaries: Vec<usize>,
    base: &'a Object,
    table: &'a Object,
}

impl Runs<'_> {
    fn append(&self, out: &mut String, start: usize, end: usize, id: &Value) -> Option<()> {
        if end <= start
            || matches!(id, Value::Null | Value::Bool(false))
            || id.as_str() == Some("0")
            || matches!(id,Value::Number(n) if !n.truthy())
        {
            return Some(());
        }
        if id.is_object() || id.is_array() {
            return None;
        }
        let key = PythonJson::string(id);
        let Some(style) = self.table.get(&key).and_then(Value::as_object) else {
            return Some(());
        };
        let node_id = self
            .node
            .get("id")
            .map(PythonJson::string)
            .unwrap_or_default();
        let mut row = Object::new();
        row.insert("nodeId".into(), Value::String(Target::normalize(&node_id)?));
        row.insert(
            "nodeName".into(),
            self.node
                .get("name")
                .cloned()
                .unwrap_or_else(|| Value::String(String::new())),
        );
        let mut range = Object::new();
        for (name, index) in [("start", start), ("end", end)] {
            range.insert(
                name.into(),
                Value::Number(Number::Integer(index.to_string())),
            );
        }
        row.insert("range".into(), Value::Object(range));
        let byte = |index| {
            self.boundaries
                .get(index)
                .copied()
                .unwrap_or(self.text.len())
        };
        row.insert(
            "text".into(),
            Value::String(self.text[byte(start)..byte(end)].to_owned()),
        );
        row.insert("overrideId".into(), Value::String(key));
        row.insert(
            "resolvedStyle".into(),
            Value::Object(text_style::project(self.base, Some(style))?),
        );
        let encoded = PythonJson::render(&Value::Object(row), false, false)?;
        if out.len() + encoded.len() + 3 > LIMIT {
            return None;
        }
        if out.len() > 1 {
            out.push_str(", ");
        }
        out.push_str(&encoded);
        Some(())
    }
}

pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    if text.len() > LIMIT {
        return None;
    }
    let input = PythonJson::parse(text)?;
    let empty = Object::new();
    let mut out = String::from("[");
    for node in input.as_array()? {
        node.as_object()?;
        if node["type"].as_str() != Some("TEXT") {
            continue;
        }
        let (Some(ids), Some(table)) = (
            node["characterStyleOverrides"].as_array(),
            node["styleOverrideTable"].as_object(),
        ) else {
            continue;
        };
        let Some(mut current) = ids.first() else {
            continue;
        };
        let characters = node
            .get("characters")
            .map(PythonJson::string)
            .unwrap_or_default();
        if characters.is_empty() {
            continue;
        }
        let boundaries: Vec<_> = characters.char_indices().map(|(i, _)| i).collect();
        let final_end = ids.len().min(boundaries.len());
        let runs = Runs {
            node,
            text: characters,
            boundaries,
            base: node["style"].as_object().unwrap_or(&empty),
            table,
        };
        let mut start = 0;
        for (i, next) in ids.iter().enumerate().skip(1) {
            if !same(current, next)? {
                runs.append(&mut out, start, i, current)?;
                current = next;
                start = i;
            }
        }
        runs.append(&mut out, start, final_end, current)?;
    }
    out.push(']');
    Some(json!({"rows_json":out}))
}
