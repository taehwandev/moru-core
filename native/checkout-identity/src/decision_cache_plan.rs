//! owner: canonical research decision request sizing and cache identity.
//! allowed imports: bounded JSON, Python JSON serialization, SHA-256 and decision cache operations.
//! forbidden imports: provider calls, credentials and direct filesystem writes.
//! callers/tests: microsoft_decision.py; test_decision_cache_plan.
//! verification: exact Python digest and byte length for existing caches.
use crate::{
    decision_cached_result::DecisionCachedResult,
    decision_input::DecisionInput,
    decision_report::DecisionReport,
    decision_response::DecisionResponse,
    pretool_guard::CallbackGuard,
    python_json::{Number, Object, PythonJson, Value as PythonValue},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    io::{self, Read, Write},
    path::Path,
};

const MAX_MESSAGE: usize = 1024 * 1024;
const MAX_CANONICAL_BYTES: usize = 4 * MAX_MESSAGE;

pub(crate) struct DecisionCachePlan;

impl DecisionCachePlan {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || !matches!(
                args[1].to_str(),
                Some(
                    "prepare"
                        | "validate-prepare"
                        | "read-prepare-input"
                        | "summarize"
                        | "validate-response"
                        | "validate-cached"
                        | "read-cached-file"
                        | "cache-write-support"
                        | "write-cached-file"
                )
            )
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
        let Some(result) = serde_json::from_slice(&raw).ok().and_then(|value| {
            if args[1] == "summarize" {
                return DecisionReport::summarize(&value);
            }
            if args[1] == "validate-response" {
                return DecisionResponse::verdict(&value);
            }
            if args[1] == "validate-cached" {
                return DecisionCachedResult::verdict(&value);
            }
            if args[1] == "read-cached-file" {
                return DecisionCachedResult::read(&value);
            }
            if args[1] == "cache-write-support" {
                return Some(json!({"supported": true}));
            }
            if args[1] == "write-cached-file" {
                return DecisionCachedResult::replace(&value);
            }
            if args[1] == "read-prepare-input" {
                return Self::prepare_file(value);
            }
            if args[1] == "validate-prepare" {
                if let Err(error) = DecisionInput::validate(&value) {
                    return Some(json!({"error": error}));
                }
            }
            Self::prepare(&value).map(|rows| json!({"rows": rows}))
        }) else {
            return 125;
        };
        let reply_failure = if args[1] == "write-cached-file" {
            1
        } else {
            125
        };
        let Ok(reply) = serde_json::to_vec(&json!({"schema_version": 1, "result": result})) else {
            return reply_failure;
        };
        if reply.len() > MAX_MESSAGE {
            return reply_failure;
        }
        i32::from(io::stdout().write_all(&reply).is_err())
    }

    fn prepare_file(mut request: Value) -> Option<Value> {
        let path = Path::new(request.get("path")?.as_str()?);
        let input = DecisionInput::read(path)?;
        if let Err(error) = DecisionInput::validate(&input) {
            return Some(json!({"error": error}));
        }
        let input = DecisionInput::project(&input)?;
        request["query"] = input["query"].clone();
        request["sources"] = input["sources"].clone();
        let rows = Self::prepare(&request)?;
        Some(json!({"payload": input, "rows": rows}))
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
                let source: serde_json::Map<_, _> = source
                    .as_object()?
                    .iter()
                    .filter(|(key, _)| {
                        ["url", "title", "text", "published_at"].contains(&key.as_str())
                    })
                    .map(|(key, value)| (key.clone(), value.clone()))
                    .collect();
                if !source.values().all(Value::is_string) {
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
