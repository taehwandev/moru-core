//! owner: scheduler recovery and attempt decisions; allowed: JSON, typed time and integers;
//! forbidden: I/O, clocks, locks, authority, dispatch or state writes;
//! callers/tests: agent_scheduler and native scheduler parity.
use super::maintenance_retention::MaintenanceRetention;
use serde_json::{json, Value};

pub(super) struct SchedulerRecovery;

impl SchedulerRecovery {
    pub(super) fn stale(request: &Value) -> Option<Value> {
        let cutoff = MaintenanceRetention::stamp(request.get("cutoff")?)?;
        let mut indexes = Vec::new();
        for (index, task) in request.get("tasks")?.as_array()?.iter().enumerate() {
            let task = task.as_object()?;
            match task.get("state") {
                Some(Value::String(state)) if matches!(state.as_str(), "queued" | "running") => {}
                Some(Value::Array(_) | Value::Object(_)) => return None,
                _ => continue,
            }
            let updated = MaintenanceRetention::stamp(task.get("updated_at")?)?;
            if updated.compare(&cutoff)?.is_lt() {
                indexes.push(index);
            }
        }
        Some(json!({"indexes": indexes}))
    }

    pub(super) fn next_attempt(request: &Value) -> Option<Value> {
        let expected = request.get("expected_attempt")?;
        let attempt = request.get("attempt")?.as_i64()?;
        if !expected.is_null() && expected.as_i64()? != attempt {
            return Some(json!({"next_attempt": null}));
        }
        if request.get("require_partial")?.as_bool()? && !request.get("has_partial")?.as_bool()? {
            return Some(json!({"next_attempt": null}));
        }
        let limit = request.get("max_attempts")?.as_i64()?;
        let next = (attempt < limit).then(|| attempt + 1);
        Some(json!({"next_attempt": next}))
    }
}
