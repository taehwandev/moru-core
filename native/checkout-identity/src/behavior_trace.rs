// owner: BehaviorTrace normalization; allowed imports: serde_json, std; forbidden imports: IO, process, providers, workflow; callers/tests: launcher trace probe and behavior_trace_tests.rs; verification: adversarial unit tests and evaluator integration.

use serde_json::{json, Map, Value};

const MAX_CASE_ID_LEN: usize = 80;
const MAX_EVENTS_LEN: usize = 2048;

pub(crate) struct BehaviorTrace;

impl BehaviorTrace {
    pub(crate) fn normalize(input: &serde_json::Value) -> Result<serde_json::Value, &'static str> {
        let obj = input.as_object().ok_or("invalid_input")?;
        validate_root_keys(obj)?;
        validate_schema_version(obj.get("schema_version"))?;
        let provider = validate_provider(obj.get("provider"))?;
        let case_id = validate_case_id(obj.get("case_id"))?;
        let raw_events = validate_events_slice(obj.get("events"))?;
        let events = normalize_events(raw_events)?;

        Ok(json!({
            "schema_version": 1,
            "runs": [{
                "provider": provider,
                "case_id": case_id,
                "events": events
            }]
        }))
    }
}

fn validate_root_keys(obj: &Map<String, Value>) -> Result<(), &'static str> {
    let has_all = obj.contains_key("schema_version")
        && obj.contains_key("provider")
        && obj.contains_key("case_id")
        && obj.contains_key("events");
    if obj.len() != 4 || !has_all {
        return Err("invalid_input");
    }
    Ok(())
}

fn validate_schema_version(value: Option<&Value>) -> Result<(), &'static str> {
    match value.and_then(Value::as_u64) {
        Some(1) => Ok(()),
        _ => Err("invalid_schema_version"),
    }
}

fn validate_provider(value: Option<&Value>) -> Result<&str, &'static str> {
    match value.and_then(Value::as_str) {
        Some(p) if matches!(p, "codex" | "claude" | "agy") => Ok(p),
        _ => Err("invalid_provider"),
    }
}

fn validate_case_id(value: Option<&Value>) -> Result<&str, &'static str> {
    let s = value.and_then(Value::as_str).ok_or("invalid_case_id")?;
    let valid_len = (1..=MAX_CASE_ID_LEN).contains(&s.len());
    let valid_chars = s
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
    if !valid_len || !valid_chars {
        return Err("invalid_case_id");
    }
    Ok(s)
}

fn validate_events_slice(value: Option<&Value>) -> Result<&[Value], &'static str> {
    let arr = value.and_then(Value::as_array).ok_or("invalid_events")?;
    if !(1..=MAX_EVENTS_LEN).contains(&arr.len()) {
        return Err("invalid_events");
    }
    Ok(arr.as_slice())
}

fn normalize_events(raw_events: &[Value]) -> Result<Vec<Value>, &'static str> {
    let last_idx = raw_events.len() - 1;
    let mut out = Vec::with_capacity(raw_events.len());
    let mut saw_final = false;

    for (idx, item) in raw_events.iter().enumerate() {
        let ev = item.as_object().ok_or("invalid_event")?;
        let (event_type, status) = parse_event_fields(ev)?;
        if event_type == "review.finished" {
            if saw_final || idx != last_idx {
                return Err("invalid_final_position");
            }
            let final_status = validate_final_status(status)?;
            saw_final = true;
            out.push(json!({ "kind": "final", "status": final_status }));
        } else {
            let kind = map_nonfinal_kind(event_type)?;
            if status.is_some() {
                return Err("invalid_event");
            }
            out.push(json!({ "kind": kind }));
        }
    }

    if !saw_final {
        return Err("missing_final");
    }
    Ok(out)
}

fn parse_event_fields(ev: &Map<String, Value>) -> Result<(&str, Option<&str>), &'static str> {
    if !ev.keys().all(|k| k == "event_type" || k == "status") {
        return Err("invalid_event");
    }
    let event_type = ev
        .get("event_type")
        .and_then(Value::as_str)
        .ok_or("invalid_event")?;
    let status = match ev.get("status") {
        None => None,
        Some(v) => Some(v.as_str().ok_or("invalid_event")?),
    };
    Ok((event_type, status))
}

fn validate_final_status(status: Option<&str>) -> Result<&str, &'static str> {
    match status {
        Some(s) if matches!(s, "ok" | "blocked" | "needs_inspection") => Ok(s),
        _ => Err("invalid_final_status"),
    }
}

fn map_nonfinal_kind(event_type: &str) -> Result<&'static str, &'static str> {
    match event_type {
        "review.record_initialized" => Ok("durable_record_written"),
        "review.prompt_submitted" => Ok("prompt_submitted"),
        "review.session_observed" => Ok("session_observed"),
        "review.submission_ambiguous" => Ok("submission_ambiguous"),
        "review.startup_retry" => Ok("startup_retry_before_submit"),
        "review.cancel_requested" | "task.cancelled" => Ok("cancel_requested"),
        "review.cancel_confirmed" | "worker.cancelled" => Ok("cancel_confirmed"),
        "review.empty_result" => Ok("empty_result_detected"),
        "task.claimed" => Ok("worker_started"),
        "worker.result" => Ok("run_completed"),
        "review.completed" => Ok("run_completed"),
        "worker.failure" => Ok("worker_failed"),
        _ => Err("unknown_event"),
    }
}

#[cfg(test)]
#[path = "behavior_trace_tests.rs"]
mod tests;
