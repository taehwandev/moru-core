//! owner: bounded decision cache file access and reuse validation.
//! allowed imports: bounded JSON, guarded cache file operations and timestamp arithmetic.
//! forbidden imports: credentials, provider effects and unguarded filesystem operations.
//! callers/tests: DecisionCachePlan and test_microsoft_decision.
//! verification: schema, exact key, TTL edges and Python fallback.
use crate::{atomic_sibling::AtomicSibling, decision_response::DecisionResponse};
use serde_json::{json, Value};
use std::{
    ffi::CString,
    fs::File,
    io::{self, Read},
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

const MAX_CACHE_BYTES: u64 = 256 * 1024;

pub(crate) struct DecisionCachedResult;

impl DecisionCachedResult {
    pub(crate) fn read(payload: &Value) -> Option<Value> {
        let directory =
            AtomicSibling::open_directory(Path::new(payload.get("directory")?.as_str()?))?;
        Self::read_in(&directory, payload.get("key")?.as_str()?, payload)
            .map(|(verdict, _)| verdict)
    }

    pub(crate) fn read_in(directory: &File, key: &str, payload: &Value) -> Option<(Value, f64)> {
        let name = cache_name(key)?;
        let file = match AtomicSibling::open_relative_result(directory, &name, libc::O_RDONLY) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Some((json!({"hit": false}), 0.0))
            }
            Err(_) => return None,
        };
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut content = String::new();
        file.take(MAX_CACHE_BYTES + 1)
            .read_to_string(&mut content)
            .ok()?;
        if content.len() as u64 > MAX_CACHE_BYTES {
            return None;
        }
        let entry: Value = serde_json::from_str(&content).ok()?;
        let result = &entry["result"];
        let relevance = result["answers"]["relevant"]["noul"].as_f64();
        let mut check = payload.as_object()?.clone();
        check.insert("key".into(), json!(key));
        check.insert(
            "response".into(),
            json!({
                "model": result["response_model"], "answers": result["answers"],
                "cost": result["reported_cost_usd"],
            }),
        );
        check.insert("entry".into(), entry);
        let mut verdict = Self::verdict(&Value::Object(check))?;
        if verdict["hit"].as_bool() == Some(true) {
            verdict
                .as_object_mut()?
                .insert("content".into(), Value::String(content));
            return Some((verdict, relevance?));
        }
        Some((verdict, 0.0))
    }

    pub(crate) fn replace(payload: &Value) -> Option<Value> {
        let content = payload.get("content")?.as_str()?;
        if content.len() as u64 > MAX_CACHE_BYTES {
            return None;
        }
        let entry: Value = serde_json::from_str(content).ok()?;
        if entry.get("key")?.as_str()? != payload.get("key")?.as_str()? {
            return None;
        }
        let target = cache_name(payload.get("key")?.as_str()?)?;
        let path = payload.get("directory")?.as_str()?;
        let create = match payload.get("create_directory") {
            Some(value) => value.as_bool()?,
            None => false,
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_nanos();
        let staging = CString::new(format!(".decision-{}-{now}", std::process::id())).ok()?;
        let directory = if create {
            if path.len() + target.to_bytes().len() + 1 >= libc::PATH_MAX as usize {
                return None;
            }
            match AtomicSibling::open_or_create_directory(Path::new(path), 0o700)? {
                Ok(dir) => dir,
                Err(_) => return Some(json!({"written": false})),
            }
        } else {
            AtomicSibling::open_directory(Path::new(path))?
        };
        let written = AtomicSibling::Private
            .replace(&directory, &staging, &target, content.as_bytes())
            .is_ok();
        Some(json!({"written": written}))
    }

    pub(crate) fn verdict(payload: &Value) -> Option<Value> {
        let entry = payload.get("entry")?.as_object()?;
        let schema = payload.get("schema")?.as_i64()?;
        let key = payload.get("key")?.as_str()?;
        let now = timestamp(payload.get("now")?)?;
        let ttl = timestamp(payload.get("ttl")?)?;
        if entry.get("key").and_then(Value::as_str) != Some(key)
            || !matches_schema(entry.get("schema").unwrap_or(&Value::Null), schema)?
        {
            return Some(json!({"hit": false}));
        }
        let Some(created) = entry.get("evaluated_at").filter(|value| value.is_number()) else {
            return Some(json!({"hit": false}));
        };
        let age = now - timestamp(created)?;
        if age < 0.0 || age >= ttl {
            return Some(json!({"hit": false}));
        }
        let decision = DecisionResponse::verdict(payload)?;
        if let Some(keep_cost) = decision["keep_cost"].as_bool() {
            Some(json!({"hit": true, "keep_cost": keep_cost}))
        } else if decision["error"].is_string() {
            Some(json!({"hit": false}))
        } else {
            None
        }
    }
}

fn cache_name(key: &str) -> Option<CString> {
    if key.len() != 64
        || !key
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        return None;
    }
    CString::new(format!("{key}.json")).ok()
}

fn matches_schema(value: &Value, expected: i64) -> Option<bool> {
    if let Some(flag) = value.as_bool() {
        return Some(i64::from(flag) == expected);
    }
    if let Some(integer) = value.as_i64() {
        return Some(integer == expected);
    }
    if let Some(integer) = value.as_u64() {
        return Some(u64::try_from(expected).ok() == Some(integer));
    }
    if value.is_f64() {
        return Some(timestamp(value)? == timestamp(&json!(expected))?);
    }
    Some(false)
}

fn timestamp(value: &Value) -> Option<f64> {
    let number = value.as_f64()?;
    // Keep integer subtraction exact, and leave extreme or nonfinite clocks
    // to Python's original number handling.
    (number.is_finite() && number.abs() <= 4_503_599_627_370_496.0).then_some(number)
}
