//! owner: OverheadFormat; allowed imports: lossless JSON values and pure report formatter;
//! forbidden imports: I/O, writes, Python processes; callers/tests: overhead format probe;
//! verification: response text parity and unsupported numeric/container refusal.
use crate::{
    overhead_report_text::OverheadReportText,
    python_json::{Number, Value},
};
use serde_json::{json, Map, Value as Json};
pub(crate) struct OverheadFormat;
impl OverheadFormat {
    pub(crate) fn format(payload: &Value) -> Option<Json> {
        let report = Self::standard(&payload["report"], 0)?;
        let text = match payload["format"].as_str()? {
            "json" => OverheadReportText::json(&report)?,
            "markdown" => OverheadReportText::markdown(&report)?,
            _ => return None,
        };
        Some(json!({"text":text}))
    }
    fn standard(value: &Value, depth: usize) -> Option<Json> {
        if depth > 128 {
            return None;
        }
        Some(match value {
            Value::Null => Json::Null,
            Value::Bool(value) => json!(value),
            Value::String(value) => json!(value),
            Value::Number(Number::Integer(value)) => json!(value.parse::<i64>().ok()?),
            Value::Number(Number::Float(value)) if value.is_finite() => json!(value),
            Value::Number(_) => return None,
            Value::Array(values) => Json::Array(
                values
                    .iter()
                    .map(|v| Self::standard(v, depth + 1))
                    .collect::<Option<Vec<_>>>()?,
            ),
            Value::Object(values) => {
                let mut result = Map::new();
                for (key, value) in values.iter() {
                    result.insert(key.clone(), Self::standard(value, depth + 1)?);
                }
                Json::Object(result)
            }
        })
    }
}
