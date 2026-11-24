//! owner: validate an already-read decision cache entry without changing its values.
//! allowed imports: bounded JSON, response validation and timestamp arithmetic.
//! forbidden imports: cache file access, credentials and provider effects.
//! callers/tests: DecisionCachePlan and test_microsoft_decision.
//! verification: schema, exact key, TTL edges and Python fallback.
use crate::decision_response::DecisionResponse;
use serde_json::{json, Value};

pub(crate) struct DecisionCachedResult;

impl DecisionCachedResult {
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
