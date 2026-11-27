//! Owner: summarize projected Figma layout-node visibility.
//! Allowed imports: Python JSON semantics and the probe receipt. Forbidden: file/network I/O.
//! Callers/tests: Figma visibility analysis and native inventory parity checks.
use crate::python_json::{Object, PythonJson, Value};
use serde_json::json;

fn excluded(node: &Value, id: &Value) -> Value {
    let mut row = Object::new();
    row.insert("id".into(), id.clone());
    for key in ["name", "type"] {
        row.insert(
            key.into(),
            node.get(key)
                .cloned()
                .unwrap_or_else(|| Value::String(String::new())),
        );
    }
    row.insert(
        "reasons".into(),
        node.get("visibilityReasons")
            .cloned()
            .unwrap_or_else(|| Value::Array(Vec::new())),
    );
    Value::Object(row)
}

pub(super) fn build(text: &str) -> Option<serde_json::Value> {
    let nodes = PythonJson::parse(text)?;
    let mut rendered = Vec::new();
    let mut hidden = Vec::new();
    for node in nodes.as_array()? {
        node.as_object()?;
        let Some(id) = node.get("id").filter(|id| PythonJson::truthy(id)) else {
            continue;
        };
        match node.get("effectiveVisible") {
            Some(Value::Bool(true)) => rendered.push(id.clone()),
            Some(Value::Bool(false)) => hidden.push(excluded(node, id)),
            _ => {}
        }
    }
    let mut inventory = Object::new();
    inventory.insert("renderedNodeIds".into(), Value::Array(rendered));
    inventory.insert("excludedNodes".into(), Value::Array(hidden));
    Some(json!({"inventory_json": PythonJson::render(&Value::Object(inventory), false, false)?}))
}
