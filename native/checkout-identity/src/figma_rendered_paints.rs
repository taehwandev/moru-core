//! Owner: Figma rendered paint summaries. Allowed imports: ordered JSON and layout rounding.
//! Forbidden: filesystem and network. Verification: layout paint parity fixtures.
use super::{super::number::round_number, round_value};
use crate::python_json::{Number, Object, PythonJson, Value};

fn rounded(value: &Value) -> Option<Value> {
    match value {
        Value::Number(number) => Some(Value::Number(round_number(number)?)),
        _ => Some(Value::Null),
    }
}

fn channel(value: &Value, default: f64) -> Option<f64> {
    match value {
        Value::Number(number) => number.as_float().filter(|n| n.is_finite()),
        Value::Bool(value) => Some(u8::from(*value) as f64),
        Value::String(_) => None, // Python accepts additional numeric spellings.
        _ => Some(default),
    }
}

fn byte(value: f64) -> Option<u8> {
    let scaled = value * 255.0;
    scaled
        .is_finite()
        .then(|| scaled.round_ties_even().clamp(0.0, 255.0) as u8)
}

fn hex(color: &Value, opacity: f64) -> Option<Option<String>> {
    let (Some(r), Some(g), Some(b)) = (color.get("r"), color.get("g"), color.get("b")) else {
        return Some(None);
    };
    let mut text = format!(
        "#{:02X}{:02X}{:02X}",
        byte(channel(r, 0.0)?)?,
        byte(channel(g, 0.0)?)?,
        byte(channel(b, 0.0)?)?
    );
    let alpha = opacity * channel(&color["a"], 1.0)?;
    if alpha < 0.995 {
        text.push_str(&format!("{:02X}", byte(alpha)?));
    }
    Some(Some(text))
}

fn items(value: &Value) -> Option<&[Value]> {
    if !PythonJson::truthy(value) {
        return Some(&[]);
    }
    value.as_array().map(Vec::as_slice)
}

fn coordinate(handle: &Value, axis: &str) -> Option<f64> {
    let Value::Number(number) = &handle[axis] else {
        return None;
    };
    number.as_float()
}

fn gradient(paint: &Value, kind: &str) -> Option<Value> {
    let alpha = channel(&paint["opacity"], 1.0)?;
    let mut stops = Vec::new();
    for stop in items(&paint["gradientStops"])?
        .iter()
        .filter(|v| v.is_object())
    {
        let mut row = Object::new();
        row.insert("position".into(), rounded(&stop["position"])?);
        row.insert(
            "hex".into(),
            hex(&stop["color"], alpha)?
                .map(Value::String)
                .unwrap_or(Value::Null),
        );
        stops.push(Value::Object(row));
    }
    let mut handles = Vec::new();
    for handle in items(&paint["gradientHandlePositions"])?
        .iter()
        .filter(|v| v.is_object())
    {
        let mut row = Object::new();
        for axis in ["x", "y"] {
            row.insert(axis.into(), rounded(&handle[axis])?);
        }
        handles.push(Value::Object(row));
    }
    let mut result = Object::new();
    result.insert("type".into(), Value::String(kind.into()));
    result.insert("stops".into(), Value::Array(stops));
    let mut angle = None;
    if kind == "GRADIENT_LINEAR" && handles.len() >= 2 {
        let [x, y, u, v] = [
            coordinate(&handles[0], "x"),
            coordinate(&handles[0], "y"),
            coordinate(&handles[1], "x"),
            coordinate(&handles[1], "y"),
        ];
        if let (Some(x), Some(y), Some(u), Some(v)) = (x, y, u, v) {
            let (dx, dy) = (u - x, v - y);
            if dx.abs() >= 1e-6 || dy.abs() >= 1e-6 {
                angle = Some(round_number(&Number::Float(
                    (dx.atan2(-dy).to_degrees() + 360.0) % 360.0,
                ))?);
            }
        } else if handles[..2].iter().all(|h| {
            ["x", "y"]
                .iter()
                .all(|k| matches!(&h[*k], Value::Number(_)))
        }) {
            return None;
        }
    }
    result.insert("handlePositions".into(), Value::Array(handles));
    if let Some(angle) = angle {
        result.insert("angleDegrees".into(), Value::Number(angle));
    }
    Some(Value::Object(result))
}

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
            let Some(text) = hex(&paint["color"], channel(&paint["opacity"], 1.0)?)? else {
                return Some(None);
            };
            if text.len() == 9 && text.ends_with("00") {
                return Some(None);
            }
            row.insert("hex".into(), Value::String(text));
        }
        "GRADIENT_LINEAR" | "GRADIENT_RADIAL" | "GRADIENT_ANGULAR" | "GRADIENT_DIAMOND" => {
            row.insert("gradient".into(), gradient(paint, kind)?);
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
        _ => {}
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
        if let Some(text) = hex(color, 1.0)? {
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
