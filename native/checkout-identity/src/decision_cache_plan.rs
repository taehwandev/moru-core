//! owner: canonical research decision request sizing and cache identity.
//! allowed imports: bounded JSON, Python JSON serialization and SHA-256.
//! forbidden imports: provider calls, credentials, cache and filesystem writes.
//! callers/tests: microsoft_decision.py; test_decision_cache_plan.
//! verification: exact Python digest and byte length for existing caches.
use crate::{
    pretool_guard::CallbackGuard,
    python_json::{Number, Object, PythonJson, Value as PythonValue},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    io::{self, Read, Write},
};

const MAX_MESSAGE: usize = 1024 * 1024;
const MAX_CANONICAL_BYTES: usize = 4 * MAX_MESSAGE;

pub(crate) struct DecisionCachePlan;

impl DecisionCachePlan {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || args[1] != "prepare"
            || CallbackGuard::root(launcher, "decision-cache-plan").is_none()
        {
            return 125;
        }
        let mut raw = Vec::new();
        if io::stdin()
            .take((MAX_MESSAGE + 1) as u64)
            .read_to_end(&mut raw)
            .is_err()
            || raw.len() > MAX_MESSAGE
        {
            return 125;
        }
        let Some(rows) = serde_json::from_slice(&raw)
            .ok()
            .and_then(|value| Self::prepare(&value))
        else {
            return 125;
        };
        let Ok(reply) = serde_json::to_vec(&json!({"schema_version": 1, "result": {"rows": rows}}))
        else {
            return 125;
        };
        if reply.len() > MAX_MESSAGE {
            return 125;
        }
        i32::from(io::stdout().write_all(&reply).is_err())
    }

    fn prepare(input: &Value) -> Option<Vec<Value>> {
        let query = input.get("query")?.as_str()?;
        let model = input.get("model")?.as_str()?;
        let endpoint = input.get("endpoint")?.as_str()?;
        let schema = input.get("schema")?.as_i64()?;
        let questions = input.get("questions")?.as_object()?;
        let mut total = 0usize;
        input
            .get("sources")?
            .as_array()?
            .iter()
            .map(|source| {
                if !source.as_object()?.values().all(Value::is_string) {
                    return None;
                }
                let request = json!({
                    "model": model, "state": {"query": query, "source": source},
                    "questions": questions, "provider": {"allow_fallbacks": false},
                });
                let bytes = encode(&request)?.len();
                total = total.checked_add(bytes)?;
                if total > MAX_CANONICAL_BYTES {
                    return None;
                }
                let cached = &json!({"schema": schema, "endpoint": endpoint, "request": request});
                let key = format!("{:x}", Sha256::digest(encode(cached)?));
                Some(json!([key, bytes]))
            })
            .collect()
    }
}

fn encode(value: &Value) -> Option<String> {
    PythonJson::render(&sorted_value(value)?, false, false)
}

fn sorted_value(value: &Value) -> Option<PythonValue> {
    match value {
        Value::Object(map) => {
            let mut entries: Vec<_> = map.iter().collect();
            entries.sort_unstable_by(|(a, _), (b, _)| a.cmp(b));
            let mut ordered = Object::new();
            for (key, value) in entries {
                ordered.insert(key.clone(), sorted_value(value)?);
            }
            Some(PythonValue::Object(ordered))
        }
        Value::Array(items) => Some(PythonValue::Array(
            items.iter().map(sorted_value).collect::<Option<_>>()?,
        )),
        Value::Number(number) if number.is_i64() || number.is_u64() => Some(PythonValue::Number(
            Number::from_token(&number.to_string(), 0)?,
        )),
        Value::Number(_) => None,
        Value::Null => Some(PythonValue::Null),
        Value::Bool(value) => Some(PythonValue::Bool(*value)),
        Value::String(value) => Some(PythonValue::String(value.clone())),
    }
}
