//! owner: MemoryJson; allowed imports: shared PythonJson, serde_json, SHA256;
//! forbidden imports: IO/process/store authority; callers/tests: memory readers;
//! verification: original byte decoder, metadata types and digest oracles.
use crate::python_json::{Number, ParseOutcome, PythonJson, Value as Source};
use serde_json::Value;
use sha2::{Digest, Sha256};
pub(crate) struct MemoryJson;
impl MemoryJson {
    pub(crate) fn decode(bytes: &[u8]) -> Option<Option<Value>> {
        let text = match std::str::from_utf8(bytes) {
            Ok(text) => text,
            Err(_) => return Some(None),
        };
        match PythonJson::parse_outcome(text) {
            ParseOutcome::Invalid => Some(None),
            ParseOutcome::Unsupported => None,
            ParseOutcome::Value(value) => Self::convert(value).map(Some),
        }
    }
    fn convert(value: Source) -> Option<Value> {
        Some(match value {
            Source::Null => Value::Null,
            Source::Bool(v) => Value::Bool(v),
            Source::String(v) => Value::String(v),
            Source::Number(Number::Integer(v)) => {
                if let Ok(number) = v.parse::<i64>() {
                    Value::from(number)
                } else {
                    Value::from(v.parse::<u64>().ok()?)
                }
            }
            Source::Number(Number::Float(v)) => Value::Number(serde_json::Number::from_f64(v)?),
            Source::Array(v) => {
                Value::Array(v.into_iter().map(Self::convert).collect::<Option<_>>()?)
            }
            Source::Object(v) => {
                let mut result = serde_json::Map::new();
                for (key, value) in v.iter() {
                    result.insert(key.clone(), Self::convert(value.clone())?);
                }
                Value::Object(result)
            }
        })
    }
    pub(crate) fn digest(record: &Value) -> Option<String> {
        let mut fields = serde_json::Map::new();
        for key in ["body", "source", "scope", "review_on"] {
            fields.insert(key.into(), record.get(key)?.clone());
        }
        for key in ["source_files", "analysis", "applies_when", "not_when"] {
            if let Some(value) = record.get(key) {
                fields.insert(key.into(), value.clone());
            }
        }
        let text = Self::canonical(&Value::Object(fields))?;
        Some(format!("{:x}", Sha256::digest(text.as_bytes())))
    }
    fn canonical(value: &Value) -> Option<String> {
        match value {
            Value::String(text) => serde_json::to_string(text).ok(),
            Value::Array(values) => Some(format!(
                "[{}]",
                values
                    .iter()
                    .map(Self::canonical)
                    .collect::<Option<Vec<_>>>()?
                    .join(", ")
            )),
            Value::Object(values) => {
                let mut keys: Vec<_> = values.keys().collect();
                keys.sort();
                Some(format!(
                    "{{{}}}",
                    keys.into_iter()
                        .map(|key| Some(format!(
                            "{}: {}",
                            serde_json::to_string(key).ok()?,
                            Self::canonical(&values[key])?
                        )))
                        .collect::<Option<Vec<_>>>()?
                        .join(", ")
                ))
            }
            _ => None, // Valid digest fields contain only strings and containers.
        }
    }
}
