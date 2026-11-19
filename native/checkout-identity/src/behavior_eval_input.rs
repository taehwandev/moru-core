//! owner: offline grader input schemas; allowed imports: PythonJson, PythonText and std collections.
//! forbidden imports: file IO, subprocesses, providers or workflow state.
//! callers/tests: offline evaluator CLI; verification: Python case and trace schema parity.
use crate::{
    python_json::{Number, Object, PythonJson, Value},
    python_text::PythonText,
};
use std::collections::{HashMap, HashSet};

pub(crate) struct BehaviorEvalInput;

impl BehaviorEvalInput {
    pub(crate) const PROVIDERS: [&'static str; 3] = ["codex", "claude", "agy"];

    pub(crate) fn providers(value: &[String]) -> Result<Vec<&str>, String> {
        let mut result = Vec::new();
        for token in value.iter().flat_map(|arg| arg.split(',')) {
            let token = token.trim_matches(PythonText::whitespace);
            if token.is_empty() {
                return Err("empty provider token in --providers".into());
            }
            if !Self::PROVIDERS.contains(&token) || result.contains(&token) {
                return Err(format!(
                    "invalid or duplicate provider: {}",
                    PythonText::repr(token)
                ));
            }
            result.push(token);
        }
        if result.is_empty() {
            return Err("providers must not be empty".into());
        }
        Ok(result)
    }

    pub(crate) fn cases(doc: &Value) -> Result<Vec<Value>, String> {
        let mut ids = HashSet::new();
        Self::envelope(doc, "cases")?
            .iter()
            .map(|raw| {
                let case = raw.as_object().ok_or("malformed case entry")?;
                if case.iter().any(|(k, _)| {
                    ![
                        "id",
                        "expected_status",
                        "max_prompts",
                        "required_events",
                        "forbidden_events",
                        "ordered_pairs",
                        "artifacts",
                    ]
                    .contains(&k.as_str())
                }) {
                    return Err("malformed case entry".into());
                }
                let (Some(id), Some(status), Some(max)) = (
                    case.get("id"),
                    case.get("expected_status"),
                    case.get("max_prompts"),
                ) else {
                    return Err("case missing required keys".into());
                };
                let cid = Self::identifier(id)
                    .filter(|s| !s.contains(['/', '\\']) && !matches!(*s, "." | ".."));
                if !cid.is_some_and(|id| ids.insert(id)) {
                    return Err(format!("invalid or duplicate case id: {}", PythonJson::repr(id)));
                }
                if !Self::status(status)
                    || !matches!(max, Value::Number(Number::Integer(text)) if !text.starts_with('-'))
                {
                    return Err("invalid expected_status or max_prompts".into());
                }
                let mut result = case.clone();
                for (field, fallback) in [
                    ("ordered_pairs", Value::Array(Vec::new())),
                    ("artifacts", Value::Object(Object::new())),
                    ("required_events", Value::Array(Vec::new())),
                    ("forbidden_events", Value::Array(Vec::new())),
                ] {
                    if !result.contains_key(field) {
                        result.insert(field.to_owned(), fallback);
                    }
                }
                let result = Value::Object(result);
                if !result["ordered_pairs"].as_array().is_some_and(|pairs| {
                    pairs.iter().all(|p| {
                        p.as_array().is_some_and(|pair| {
                            pair.len() == 2 && pair.iter().all(|v| Self::identifier(v).is_some())
                        })
                    })
                }) {
                    return Err("invalid ordered_pairs".into());
                }
                if !result["artifacts"].as_object().is_some_and(|files| {
                    files
                        .iter()
                        .all(|(k, v)| !k.is_empty() && !k.contains('\0') && v.as_str().is_some())
                }) {
                    return Err("artifacts must map relative paths to literal strings".into());
                }
                for field in ["required_events", "forbidden_events"] {
                    if !result[field]
                        .as_array()
                        .is_some_and(|list| list.iter().all(|v| Self::identifier(v).is_some()))
                    {
                        return Err(format!("{field} must be a list of non-empty strings"));
                    }
                }
                Ok(result)
            })
            .collect()
    }

    pub(crate) fn runs<'a>(
        doc: &'a Value,
        cases: &[Value],
    ) -> Result<HashMap<(&'a str, &'a str), &'a [Value]>, String> {
        let ids: HashSet<_> = cases
            .iter()
            .filter_map(|case| case["id"].as_str())
            .collect();
        let mut runs = HashMap::new();
        for raw in Self::envelope(doc, "runs")? {
            raw.as_object()
                .filter(|run| {
                    run.len() == 3
                        && ["provider", "case_id", "events"]
                            .iter()
                            .all(|k| run.contains_key(*k))
                })
                .ok_or("malformed run entry")?;
            let provider_value = &raw["provider"];
            let id_value = &raw["case_id"];
            let provider = provider_value
                .as_str()
                .filter(|p| Self::PROVIDERS.contains(p))
                .ok_or_else(|| format!("unknown provider: {}", PythonJson::repr(provider_value)))?;
            let id = id_value
                .as_str()
                .filter(|id| ids.contains(id) && !runs.contains_key(&(provider, *id)))
                .ok_or_else(|| {
                    format!(
                        "unknown or duplicate run: {provider}/{}",
                        PythonJson::repr(id_value)
                    )
                })?;
            let events = raw["events"].as_array().ok_or("events must be a list")?;
            for value in events {
                let event = value.as_object().ok_or("malformed event entry")?;
                let kind = event
                    .get("kind")
                    .and_then(Self::identifier)
                    .ok_or("malformed event entry")?;
                if kind == "final" {
                    if event.len() != 2 || !event.get("status").is_some_and(Self::status) {
                        return Err("invalid final event".into());
                    }
                } else if event.len() != 1 {
                    return Err("status is only valid on final events".into());
                }
            }
            runs.insert((provider, id), events.as_slice());
        }
        Ok(runs)
    }

    fn envelope<'a>(doc: &'a Value, name: &str) -> Result<&'a [Value], String> {
        doc.as_object()
            .filter(|o| o.len() == 2 && o.contains_key(name) && o.contains_key("schema_version"))
            .ok_or_else(|| format!("malformed {name} document schema"))?;
        if !matches!(doc["schema_version"], Value::Number(Number::Integer(ref text)) if text == "1")
        {
            return Err(format!("unsupported {name} schema_version"));
        }
        doc[name]
            .as_array()
            .filter(|list| !list.is_empty())
            .map(Vec::as_slice)
            .ok_or_else(|| format!("{name} must be a non-empty list"))
    }

    fn identifier(value: &Value) -> Option<&str> {
        value
            .as_str()
            .filter(|s| !s.contains('\0') && s.chars().any(|c| !PythonText::whitespace(c)))
    }

    fn status(value: &Value) -> bool {
        matches!(value.as_str(), Some("ok" | "blocked" | "needs_inspection"))
    }
}
