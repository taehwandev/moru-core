//! owner: ordered Figma asset candidate extraction and vector geometry hashing;
//! allowed imports: ordered Python JSON, Figma node IDs and SHA-1; forbidden
//! imports: filesystem and network; callers/tests: guarded asset candidate probe
//! and offline extraction fixtures.
use super::target::Target;
use crate::python_json::{Object, PythonJson, Value};
use sha1::{Digest, Sha1};

const SIGNATURE: &[&str] = &[
    "type",
    "name",
    "size",
    "absoluteBoundingBox",
    "fills",
    "strokes",
    "strokeWeight",
    "strokeAlign",
    "individualStrokeWeights",
    "cornerRadius",
    "rectangleCornerRadii",
    "effects",
    "opacity",
    "blendMode",
    "fillGeometry",
    "strokeGeometry",
];

fn sorted(value: &Value) -> Value {
    match value {
        Value::Object(fields) => {
            let mut entries: Vec<_> = fields.iter().collect();
            entries.sort_unstable_by(|a, b| a.0.cmp(b.0));
            let mut ordered = Object::new();
            for (key, v) in entries {
                ordered.insert(key.clone(), sorted(v));
            }
            Value::Object(ordered)
        }
        Value::Array(items) => Value::Array(items.iter().map(sorted).collect()),
        other => other.clone(),
    }
}

fn dedup(node: &Value, refs: &[String]) -> Option<String> {
    if !refs.is_empty() {
        let mut ordered: Vec<_> = refs.iter().map(String::as_str).collect();
        ordered.sort_unstable();
        return Some(format!("img:{}", ordered.join(",")));
    }
    let mut signature = Object::new();
    for key in SIGNATURE {
        if let Some(v) = node.get(key) {
            signature.insert((*key).into(), v.clone());
        }
    }
    let bytes = PythonJson::render(&sorted(&Value::Object(signature)), false, true)?;
    Some(format!("vec:{:x}", Sha1::digest(bytes.as_bytes())))
}

fn field(row: &Value, key: &str) -> Value {
    row.get(key)
        .cloned()
        .unwrap_or_else(|| Value::String(String::new()))
}

fn candidate(node: &Value) -> Option<Option<Value>> {
    node.as_object()?;
    let export = node.get("exportSettings").filter(|v| PythonJson::truthy(v));
    let mut refs = Vec::new();
    for key in ["fills", "strokes"] {
        if let Some(paints) = node.get(key).filter(|v| PythonJson::truthy(v)) {
            for p in paints.as_array()? {
                if p["type"].as_str() == Some("IMAGE") && PythonJson::truthy(&p["imageRef"]) {
                    refs.push(PythonJson::string(&p["imageRef"]));
                }
            }
        }
    }
    let kind = field(node, "type");
    if matches!(kind, Value::Array(_) | Value::Object(_)) {
        return None;
    }
    if export.is_none()
        && refs.is_empty()
        && !matches!(kind.as_str(), Some("VECTOR" | "BOOLEAN_OPERATION"))
    {
        return Some(None);
    }
    let id = Target::normalize(&PythonJson::string(&field(node, "id")))?;
    let key = dedup(node, &refs)?;
    let mut out = Object::new();
    for (k, v) in [
        ("id", Value::String(id)),
        ("name", field(node, "name")),
        ("type", kind),
        (
            "exportSettings",
            export.cloned().unwrap_or_else(|| Value::Array(Vec::new())),
        ),
        (
            "imageRefs",
            Value::Array(refs.into_iter().map(Value::String).collect()),
        ),
        ("dedupKey", Value::String(key)),
    ] {
        out.insert(k.into(), v);
    }
    Some(Some(Value::Object(out)))
}

pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input = PythonJson::parse(text)?;
    let mut output = Vec::new();
    for node in input.as_array()? {
        if let Some(row) = candidate(node)? {
            output.push(row)
        }
    }
    let encoded = PythonJson::render(&Value::Array(output), false, false)?;
    Some(serde_json::json!({"assets_json":encoded}))
}
