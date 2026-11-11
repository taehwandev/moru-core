//! owner: MemoryRecord; allowed imports: std/JSON/shared PythonText/MemoryJson;
//! forbidden imports: IO/providers/store mutations; callers/tests: memory files,
//! recall; verification: schema/digest/condition/analysis/source-path oracles.
use crate::{memory_json::MemoryJson, python_text::PythonText};
use serde_json::Value;
use std::collections::BTreeSet;
pub(crate) struct MemoryRecord;
impl MemoryRecord {
    pub(crate) fn valid(record: &Value, name: &str) -> Option<bool> {
        let Some(object) = record.as_object() else {
            return Some(false);
        };
        let schema = object.get("schema_version");
        if schema != Some(&Value::Bool(true)) && schema.and_then(Value::as_f64) != Some(1.0) {
            return Some(false);
        }
        let Some(id) = record.get("id").and_then(Value::as_str) else {
            return Some(false);
        };
        if !Self::hex(id, 16) || name != format!("{id}.json") {
            return Some(false);
        }
        if !record
            .get("status")
            .and_then(Value::as_str)
            .is_some_and(|s| ["active", "pending", "approved", "retired"].contains(&s))
            || !record
                .get("scope")
                .and_then(Value::as_str)
                .is_some_and(Self::scope)
            || !Self::text(record.get("body"), 500)
            || !Self::text(record.get("source"), 200)
        {
            return Some(false);
        }
        let Some(review) = record.get("review_on").and_then(Value::as_str) else {
            return Some(false);
        };
        // Other Python releases accept additional ISO forms. Never misclassify
        // an unsupported date spelling as an invalid record.
        if review.len() != 10
            || review.as_bytes().get(4) != Some(&b'-')
            || review.as_bytes().get(7) != Some(&b'-')
        {
            return None;
        }
        if !Self::date(review) || review < "2000-01-01" {
            return Some(false);
        }
        if let Some(value) = record.get("replaces") {
            if Self::truthy(value) && !value.as_str().is_some_and(|s| Self::hex(s, 16)) {
                return Some(false);
            }
        }
        if record
            .get("source_files")
            .is_some_and(|value| !Self::sources(value))
            || record
                .get("analysis")
                .is_some_and(|value| !Self::analysis(value, record))
            || ["applies_when", "not_when"]
                .iter()
                .any(|key| record.get(key).is_some() && !Self::text(record.get(key), 160))
        {
            return Some(false);
        }
        Some(record.get("digest").and_then(Value::as_str) == MemoryJson::digest(record).as_deref())
    }
    fn text(value: Option<&Value>, limit: usize) -> bool {
        value.and_then(Value::as_str).is_some_and(|s| {
            !s.is_empty() && s.chars().count() <= limit && s.chars().all(PythonText::printable)
        })
    }
    fn hex(value: &str, length: usize) -> bool {
        value.len() == length
            && value
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    }
    fn sources(value: &Value) -> bool {
        let Some(files) = value.as_array() else {
            return false;
        };
        if !(1..=4).contains(&files.len()) {
            return false;
        }
        let mut seen = BTreeSet::new();
        files.iter().all(|file| {
            let Some(object) = file.as_object() else {
                return false;
            };
            let Some(path) = file.get("path").and_then(Value::as_str) else {
                return false;
            };
            object.len() == 2
                && file
                    .get("blob")
                    .and_then(Value::as_str)
                    .is_some_and(|s| Self::hex(s, 40) || Self::hex(s, 64))
                && Self::text(file.get("path"), 300)
                && !path.starts_with('/')
                && !path.contains('\\')
                && path
                    .split('/')
                    .all(|p| !p.is_empty() && ![".", "..", ".git"].contains(&p))
                && seen.insert(path)
        })
    }
    fn analysis(value: &Value, record: &Value) -> bool {
        let Some(object) = value.as_object() else {
            return false;
        };
        object.len() == 3
            && ["question", "context"].iter().all(|key| {
                Self::text(value.get(key), 300)
                    && value[key]
                        .as_str()
                        .is_some_and(|s| s.trim_matches(PythonText::whitespace) == s)
            })
            && value
                .get("inputs")
                .and_then(Value::as_str)
                .is_some_and(|s| Self::hex(s, 64))
            && record.get("source_files").is_some_and(Self::truthy)
    }
    fn truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(v) => *v,
            Value::Number(v) => v.as_f64() != Some(0.0),
            Value::String(v) => !v.is_empty(),
            Value::Array(v) => !v.is_empty(),
            Value::Object(v) => !v.is_empty(),
        }
    }
    pub(crate) fn scope(value: &str) -> bool {
        let raw = value.as_bytes();
        (2..=41).contains(&raw.len())
            && raw[0].is_ascii_lowercase()
            && raw[1..]
                .iter()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
    }
    pub(crate) fn date(value: &str) -> bool {
        let raw = value.as_bytes();
        if raw.len() != 10
            || raw[4] != b'-'
            || raw[7] != b'-'
            || raw
                .iter()
                .enumerate()
                .any(|(i, c)| i != 4 && i != 7 && !c.is_ascii_digit())
        {
            return false;
        }
        let year = value[..4].parse::<u32>().unwrap();
        let month = value[5..7].parse::<u32>().unwrap();
        let day = value[8..].parse::<u32>().unwrap();
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        let days = match month {
            2 => 28 + u32::from(leap),
            4 | 6 | 9 | 11 => 30,
            1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
            _ => 0,
        };
        year > 0 && day > 0 && day <= days
    }
}
