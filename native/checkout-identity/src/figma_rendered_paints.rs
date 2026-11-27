//! Owner: Figma rendered paint summaries. Allowed imports: ordered JSON and layout rounding.
//! Forbidden: filesystem and network. Verification: layout paint parity fixtures.
use super::{
    super::{number::round_number, paint::Paint},
    round_value,
};
use crate::python_json::{Object, PythonJson, Value};

fn summarize(paint: &Value) -> Option<Option<Value>> {
    if matches!(paint.get("visible"), Some(Value::Bool(false))) {
        return Some(None);
    }
    let opacity = paint.get("opacity");
    if let Some(Value::Number(n)) = opacity {
        if n.as_float()? <= 0.0 {
            return Some(None);
        }
    }
    let Some(kind) = paint["type"].as_str().filter(|s| !s.is_empty()) else {
        return Some(None);
    };
    let mut row = Object::new();
    row.insert("type".into(), Value::String(kind.into()));
    if let Some(Value::Number(n)) = opacity {
        row.insert("opacity".into(), Value::Number(round_number(n)?));
    }
    if let Some(mode) = paint["blendMode"].as_str() {
        row.insert("blendMode".into(), Value::String(mode.into()));
    }
    match kind {
        "SOLID" => {
            let Some(text) = Paint::solid(&paint["color"], &paint["opacity"])? else {
                return Some(None);
            };
            if text.len() == 9 && text.ends_with("00") {
                return Some(None);
            }
            row.insert("hex".into(), Value::String(text));
        }
        "IMAGE" => {
            for key in ["imageRef", "scaleMode"] {
                if PythonJson::truthy(&paint[key]) {
                    row.insert(key.into(), paint[key].clone());
                }
            }
            if paint["imageTransform"].is_array() {
                row.insert(
                    "imageTransform".into(),
                    round_value(&paint["imageTransform"])?,
                );
            }
        }
        _ => {
            if let Some(gradient) = Paint::gradient(paint)? {
                row.insert("gradient".into(), gradient);
            }
        }
    }
    Some(Some(Value::Object(row)))
}

pub(super) fn render(node: &Value) -> Option<Object> {
    let mut result = Object::new();
    for field in ["background", "fills", "strokes"] {
        let Some(paints) = node[field].as_array() else {
            continue;
        };
        let mut rows = Vec::new();
        for paint in paints.iter().filter(|p| p.is_object()) {
            if let Some(row) = summarize(paint)? {
                rows.push(row);
            }
        }
        if !rows.is_empty() {
            result.insert(field.into(), Value::Array(rows));
        }
    }
    if let Some(color) = node.get("backgroundColor").filter(|c| c.is_object()) {
        if let Some(text) = Paint::solid(color, &Value::Null)? {
            if !(text.len() == 9 && text.ends_with("00")) {
                let mut row = Object::new();
                row.insert("type".into(), Value::String("SOLID".into()));
                row.insert("hex".into(), Value::String(text));
                result.insert(
                    "backgroundColor".into(),
                    Value::Array(vec![Value::Object(row)]),
                );
            }
        }
    }
    Some(result)
}
