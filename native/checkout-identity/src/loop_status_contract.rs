//! owner: loop status persisted-state validation; allowed imports: PythonJson types and std;
//! forbidden imports: I/O, execution, budget mutation or ownership claims;
//! callers/tests: native loop status and Python contract parity fixtures.
use crate::python_json::{Number, Value};
use std::collections::HashSet;

const CONFIG: &[&str] = &[
    "objective",
    "owned",
    "verifiers",
    "directory",
    "goal_pattern",
    "regression_pattern",
    "max_iterations",
    "max_seconds",
    "max_model_calls",
    "metric",
];
const STATE: &[&str] = &[
    "schema_version",
    "run_id",
    "config",
    "created_at",
    "deadline",
    "updated_at",
    "status",
    "iterations",
    "model_calls",
    "accepted",
    "baseline_value",
    "attempt",
    "history",
    "baseline_result",
    "inflight",
];

pub(super) fn validate(state: &Value, run_id: &str) -> Option<()> {
    fields(state, STATE)?;
    let status = state["status"].as_str()?;
    if integer(&state["schema_version"])? != 1
        || state["run_id"].as_str()? != run_id
        || !matches!(
            status,
            "ready"
                | "attempting"
                | "checking"
                | "evaluated"
                | "paused"
                | "succeeded"
                | "exhausted"
                | "cancelled"
        )
    {
        return None;
    }
    let (max_iterations, max_seconds, max_calls) = config(&state["config"])?;
    finite(&state["updated_at"])?;
    if deadline_number(&state["created_at"])? + max_seconds as f64
        != deadline_number(&state["deadline"])?
    {
        return None;
    }
    let iterations = integer(&state["iterations"])?;
    let calls = integer(&state["model_calls"])?;
    if !(0..=max_iterations).contains(&iterations) || !(0..=max_calls).contains(&calls) {
        return None;
    }
    snapshot(&state["accepted"])?;
    optional_number(&state["baseline_value"])?;
    attempts(state, iterations, calls)?;
    let inflight = &state["inflight"];
    let active = &state["attempt"];
    if (status == "checking") != !matches!(inflight, Value::Null)
        || (matches!(status, "attempting" | "evaluated") && matches!(active, Value::Null))
    {
        return None;
    }
    if !matches!(inflight, Value::Null) {
        fields(inflight, &["owner", "groups"])?;
        positive(&inflight["owner"], 1 << 31)?;
        let groups = inflight["groups"].as_array()?;
        let ids = groups
            .iter()
            .map(|group| positive(group, 1 << 31))
            .collect::<Option<HashSet<_>>>()?;
        if groups.len() > 2 || groups.len() != ids.len() {
            return None;
        }
    }
    if !matches!(state["baseline_result"], Value::Null) {
        result(&state["baseline_result"], false)?;
    }
    Some(())
}

fn config(value: &Value) -> Option<(i64, i64, i64)> {
    fields(value, CONFIG)?;
    bounded_text(&value["objective"], 280)?;
    for key in ["directory", "goal_pattern", "regression_pattern"] {
        bounded_text(&value[key], 240)?;
    }
    for key in ["owned", "verifiers"] {
        if !(1..=64).contains(&value[key].as_array()?.len()) {
            return None;
        }
    }
    let metric = &value["metric"];
    if !matches!(metric, Value::Null) {
        fields(metric, &["direction", "min_delta"])?;
        if !matches!(metric["direction"].as_str()?, "min" | "max")
            || finite(&metric["min_delta"])? <= 0.0
        {
            return None;
        }
    }
    Some((
        positive(&value["max_iterations"], 1000)?,
        positive(&value["max_seconds"], 86400)?,
        positive(&value["max_model_calls"], 10000)?,
    ))
}

fn attempts(state: &Value, iterations: i64, calls: i64) -> Option<()> {
    let history = state["history"].as_array()?;
    let active = &state["attempt"];
    let active = (!matches!(active, Value::Null)).then_some(active);
    if history.len() + usize::from(active.is_some()) != iterations as usize
        || history
            .iter()
            .any(|entry| entry["verdict"].as_str() == Some("pending"))
    {
        return None;
    }
    let mut ids = HashSet::new();
    let mut used = 0i64;
    for entry in history.iter().chain(active) {
        fields(
            entry,
            &[
                "id",
                "hypothesis",
                "started_at",
                "calls",
                "result",
                "verdict",
            ],
        )?;
        let id = entry["id"].as_str()?;
        let verdict = entry["verdict"].as_str()?;
        if id.chars().count() != 32
            || !ids.insert(id)
            || !matches!(verdict, "pending" | "accepted" | "rejected")
        {
            return None;
        }
        used = used.checked_add(positive(&entry["calls"], calls)?)?;
        bounded_text(&entry["hypothesis"], 280)?;
        finite(&entry["started_at"])?;
        if !matches!(entry["result"], Value::Null) {
            result(&entry["result"], verdict == "pending")?;
        }
    }
    (used == calls).then_some(())
}

fn snapshot(value: &Value) -> Option<()> {
    fields(value, &["head", "index", "outside", "owned", "verifiers"])?;
    for key in ["head", "index", "outside"] {
        value[key].as_str()?;
    }
    value["owned"].as_object()?;
    value["verifiers"].as_object()?;
    Some(())
}

fn result(value: &Value, candidate: bool) -> Option<()> {
    if candidate {
        fields(
            value,
            &["regression", "goal", "value", "timely", "candidate"],
        )?;
        snapshot(&value["candidate"])?;
    } else {
        fields(value, &["regression", "goal", "value", "timely"])?;
    }
    if !matches!(value["timely"], Value::Bool(_)) {
        return None;
    }
    optional_number(&value["value"])?;
    for key in ["regression", "goal"] {
        let check = &value[key];
        fields(check, &["exit", "tests", "passed"])?;
        let exit = integer(&check["exit"])?;
        let tests = integer(&check["tests"])?;
        match check["passed"] {
            Value::Bool(false) if tests >= 0 => {}
            Value::Bool(true) if exit == 0 && tests > 0 => {}
            _ => return None,
        }
    }
    Some(())
}

fn fields(value: &Value, fields: &[&str]) -> Option<()> {
    let object = value.as_object()?;
    (object.len() == fields.len() && fields.iter().all(|key| object.contains_key(key)))
        .then_some(())
}

fn bounded_text(value: &Value, max: usize) -> Option<()> {
    let text = value.as_str()?;
    (!text.trim().is_empty() && text.chars().count() <= max && !text.chars().any(|c| c < ' '))
        .then_some(())
}

fn integer(value: &Value) -> Option<i64> {
    match value {
        Value::Number(Number::Integer(text)) => text.parse().ok(),
        _ => None,
    }
}

fn positive(value: &Value, max: i64) -> Option<i64> {
    let count = integer(value)?;
    (1..=max).contains(&count).then_some(count)
}

fn finite(value: &Value) -> Option<f64> {
    let Value::Number(number) = value else {
        return None;
    };
    let number = number.as_float()?;
    number.is_finite().then_some(number)
}

fn optional_number(value: &Value) -> Option<()> {
    if !matches!(value, Value::Null) {
        finite(value)?;
    }
    Some(())
}

fn deadline_number(value: &Value) -> Option<f64> {
    // Python can compare arbitrary-size integers exactly. Decline integer
    // deadlines outside the shared exact range, including the largest offset.
    if matches!(value, Value::Number(Number::Integer(_)))
        && integer(value)?.unsigned_abs() > (1u64 << 53) - 86400
    {
        return None;
    }
    finite(value)
}
