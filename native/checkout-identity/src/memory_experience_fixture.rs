//! owner: offline experience fixture loading and schema; allowed imports:
//! bounded file read, JSON, Unicode printability and shared scope grammar;
//! forbidden imports: writes, memory ranking and providers; callers/tests:
//! private memory probe and Python fixture parity.
use crate::{
    memory_record::MemoryRecord,
    memory_terms::MemoryTerms,
    python_input_file::{FileRead, PythonInputFile},
    python_json::{InputDiagnostic, Number as PythonNumber, PythonJson, Value as PythonValue},
    python_text::PythonText,
    text::Text,
};
use serde_json::{json, Map, Value};
use std::{collections::HashSet, ffi::OsStr};

const MAX_FIXTURE_BYTES: u64 = 512 * 1024;

const RECORD_FIELDS: &[&str] = &[
    "id",
    "body",
    "source",
    "scope",
    "status",
    "review_in_days",
    "applies_when",
    "not_when",
    "replaces",
];
const CASE_FIELDS: &[&str] = &[
    "id",
    "category",
    "scope",
    "request",
    "target_summary",
    "target_paths",
    "expected_relevant",
    "applicability_expectation",
];

pub(super) struct ExperienceFixture;

impl ExperienceFixture {
    pub(super) fn evaluate(payload: &Value) -> Option<Value> {
        let fields = payload.as_object()?;
        if fields.len() != 3 || fields.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let path = OsStr::new(fields.get("path")?.as_str()?);
        let digit_limit = usize::try_from(fields.get("digit_limit")?.as_u64()?).ok()?;
        Some(match Self::load(path, digit_limit)? {
            Ok(fixture) => json!({"fixture": fixture}),
            Err(error) => json!({"error": error}),
        })
    }

    pub(super) fn load(path: &OsStr, digit_limit: usize) -> Option<Result<Value, String>> {
        let fixture = Self::decode(path, digit_limit, false)?.ok()?;
        Some(Self::validate(&fixture).map(|()| fixture))
    }

    pub(super) fn decode(
        path: &OsStr,
        digit_limit: usize,
        diagnostics: bool,
    ) -> Option<Result<Value, String>> {
        let bytes = match PythonInputFile::read(path, MAX_FIXTURE_BYTES, false)? {
            FileRead::Bytes(bytes) => bytes,
            FileRead::Error(error) if diagnostics && path.to_str()?.is_ascii() => {
                return Some(Err(error));
            }
            _ => return None,
        };
        let text = Text::universal_newlines(std::str::from_utf8(&bytes).ok()?);
        let digit_limit = Some(digit_limit);
        match PythonJson::parse_with_diagnostic(&text, digit_limit, Some(false)) {
            Ok(Some(decoded)) => wire_value(&decoded).map(Ok),
            Err(InputDiagnostic::Syntax(error)) if diagnostics => {
                // The launcher cannot assume the consumer's JSON diagnostic profile.
                match PythonJson::parse_with_diagnostic(&text, digit_limit, Some(true)) {
                    Err(InputDiagnostic::Syntax(other)) if other == error => Some(Err(error)),
                    _ => None,
                }
            }
            _ => None,
        }
    }

    pub(super) fn validate(fixture: &Value) -> Result<(), String> {
        if fixture.get("schema_version").and_then(Value::as_i64) != Some(1) {
            return Err("fixture schema_version must be 1".into());
        }
        line(fixture.get("description"), 1000, "description")?;
        let nonempty = |key| {
            fixture
                .get(key)
                .and_then(Value::as_array)
                .filter(|items| !items.is_empty())
        };
        let (Some(records), Some(cases)) = (nonempty("records"), nonempty("cases")) else {
            return Err("fixture needs nonempty records and cases lists".into());
        };

        let mut record_ids = HashSet::new();
        for record in records {
            validate_record(
                closed(record, RECORD_FIELDS).ok_or("record contains unsupported fields")?,
                &mut record_ids,
            )?;
        }
        for record in records {
            if let Some(value) = record.get("replaces") {
                if !value.as_str().is_some_and(|id| record_ids.contains(id))
                    || record.get("id") == Some(value)
                {
                    return Err("replaces must reference another fixture record".into());
                }
            }
        }
        let mut case_ids = HashSet::new();
        for case in cases {
            validate_case(
                closed(case, CASE_FIELDS).ok_or("case contains unsupported fields")?,
                &record_ids,
                &mut case_ids,
            )?;
        }
        Ok(())
    }
}

fn wire_value(value: &PythonValue) -> Option<Value> {
    // The existing JSON transport can round-trip finite floats and integers
    // that fit its numeric envelope. Larger and nonfinite values stay in Python.
    Some(match value {
        PythonValue::Null => Value::Null,
        PythonValue::Bool(value) => Value::Bool(*value),
        PythonValue::String(value) => Value::String(value.clone()),
        PythonValue::Number(PythonNumber::Integer(digits)) => Value::Number(
            digits
                .parse::<i64>()
                .map(serde_json::Number::from)
                .or_else(|_| digits.parse::<u64>().map(serde_json::Number::from))
                .ok()?,
        ),
        PythonValue::Number(PythonNumber::Float(value)) => {
            Value::Number(serde_json::Number::from_f64(*value)?)
        }
        PythonValue::Array(items) => {
            Value::Array(items.iter().map(wire_value).collect::<Option<_>>()?)
        }
        PythonValue::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, value)| Some((key.clone(), wire_value(value)?)))
                .collect::<Option<_>>()?,
        ),
    })
}

fn validate_record<'a>(
    record: &'a Map<String, Value>,
    ids: &mut HashSet<&'a str>,
) -> Result<(), String> {
    let id = record.get("id").and_then(Value::as_str).filter(|id| {
        id.len() == 16
            && id
                .bytes()
                .all(|ch| ch.is_ascii_digit() || (b'a'..=b'f').contains(&ch))
    });
    if !id.is_some_and(|id| ids.insert(id)) {
        return Err("record ids must be unique 16-character lowercase hex strings".into());
    }
    line(record.get("body"), 500, "body")?;
    line(record.get("source"), 200, "source")?;
    scope(record.get("scope"))?;
    if record.get("status").is_some_and(|value| {
        !matches!(
            value.as_str(),
            Some("active" | "approved" | "pending" | "retired")
        )
    }) {
        return Err("record status is invalid".into());
    }
    if record.get("review_in_days").is_some_and(|value| {
        !value
            .as_i64()
            .is_some_and(|days| (-365..=365).contains(&days))
    }) {
        return Err("review_in_days must be an integer between -365 and 365".into());
    }
    for field in ["applies_when", "not_when"] {
        if let Some(value) = record.get(field) {
            line(Some(value), 160, field)?;
        }
    }
    Ok(())
}

fn validate_case<'a>(
    case: &'a Map<String, Value>,
    record_ids: &HashSet<&str>,
    case_ids: &mut HashSet<&'a str>,
) -> Result<(), String> {
    if !case_ids.insert(line(case.get("id"), 80, "case id")?) {
        return Err("case ids must be unique".into());
    }
    line(case.get("category"), 80, "category")?;
    scope(case.get("scope"))?;
    for field in ["request", "target_summary"] {
        if case.get(field).is_some_and(|value| {
            !value
                .as_str()
                .is_some_and(|text| text.chars().all(PythonText::printable))
        }) {
            return Err(format!("{field} must be a printable string"));
        }
    }
    if case.get("target_paths").is_some_and(|value| {
        !value.as_array().is_some_and(|paths| {
            paths.iter().all(|path| {
                path.as_str()
                    .is_some_and(|text| !text.is_empty() && text.chars().all(PythonText::printable))
            })
        })
    }) {
        return Err("target_paths must contain nonempty printable strings".into());
    }
    let mut expected_ids = HashSet::new();
    if !case
        .get("expected_relevant")
        .and_then(Value::as_array)
        .is_some_and(|items| {
            items.iter().all(|value| {
                value
                    .as_str()
                    .is_some_and(|id| record_ids.contains(id) && expected_ids.insert(id))
            })
        })
    {
        return Err("expected_relevant must contain unique fixture record ids".into());
    }
    if let Some(value) = case.get("applicability_expectation") {
        line(Some(value), 1000, "applicability_expectation")?;
    }
    Ok(())
}

fn closed<'a>(value: &'a Value, keys: &[&str]) -> Option<&'a Map<String, Value>> {
    let object = value.as_object()?;
    object
        .keys()
        .all(|key| keys.contains(&key.as_str()))
        .then_some(object)
}

fn line<'a>(value: Option<&'a Value>, maximum: usize, field: &str) -> Result<&'a str, String> {
    value
        .and_then(Value::as_str)
        .filter(|text| {
            !text.is_empty()
                && text.chars().count() <= maximum
                && text.chars().all(PythonText::printable)
        })
        .ok_or_else(|| format!("{field} must be one printable line of 1–{maximum} characters"))
}

fn scope(value: Option<&Value>) -> Result<(), String> {
    if value.is_some_and(|value| !value.as_str().is_some_and(MemoryRecord::scope)) {
        return Err("scope must be a workflow slug".into());
    }
    Ok(())
}
