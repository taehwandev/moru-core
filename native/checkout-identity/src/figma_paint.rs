//! Shared Figma paint projection for rendered nodes and candidate aggregation.
use super::number::round_number;
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

pub(super) struct Paint;

impl Paint {
    pub(super) fn solid(color: &Value, opacity: &Value) -> Option<Option<String>> {
        hex(color, channel(opacity, 1.0)?)
    }

    pub(super) fn gradient(paint: &Value) -> Option<Option<Value>> {
        if !paint.is_object() || matches!(&paint["visible"], Value::Bool(false)) {
            return Some(None);
        }
        match &paint["type"] {
            Value::String(kind)
                if matches!(
                    kind.as_str(),
                    "GRADIENT_LINEAR" | "GRADIENT_RADIAL" | "GRADIENT_ANGULAR" | "GRADIENT_DIAMOND"
                ) =>
            {
                Some(Some(gradient(paint, kind)?))
            }
            Value::Object(_) | Value::Array(_) => None,
            _ => Some(None),
        }
    }
}
