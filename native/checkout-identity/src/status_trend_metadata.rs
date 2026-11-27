//! Owner: project ordinary trend run sources into normalized run metadata.
//! Allowed imports: Python text and UTC helpers, SHA-256, JSON.
//! Forbidden imports: filesystem, database, network and provider clients.
//! Callers/tests: status trend completion probe and observability report tests.
use super::{status_trend_route::route_token, status_trend_stamp::utc};
use crate::{discovery_fs::DiscoveryFs, text::Text};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

// Python's "value or fallback" applied to projected scalar JSON.
fn present(value: &Value) -> Option<&Value> {
    match value {
        Value::Null | Value::Bool(false) => None,
        Value::String(s) if s.is_empty() => None,
        Value::Number(n) if n.as_i64() == Some(0) => None,
        other => Some(other),
    }
}

fn scalar(value: Option<&Value>, default: &str) -> Option<String> {
    match value {
        None => Some(default.into()),
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Bool(true)) => Some("True".into()),
        Some(Value::Number(n)) if n.is_i64() || n.is_u64() => Some(n.to_string()),
        _ => None,
    }
}

fn generation(value: Option<&Value>) -> Option<i64> {
    match value {
        None => Some(0),
        Some(Value::Number(n)) => n.as_i64(),
        Some(Value::Bool(b)) => Some(i64::from(*b)),
        // Python accepts Unicode decimal digits, separators and arbitrary
        // precision. Defer those uncommon representations to the reference.
        Some(Value::String(s)) => Text::py_strip(s).parse().ok(),
        _ => None,
    }
}

pub(super) fn project(sources: &Value) -> Option<Value> {
    let mut runs = Vec::new();
    for source in sources.get("runs")?.as_array()? {
        let [name, reg, preflight, docs, gates] = source.as_array()?.as_slice() else {
            return None;
        };
        let started = present(&reg["started_at"]).or_else(|| present(&preflight["timestamp"]));
        let started = utc(&scalar(started, "")?)?;
        if started.is_empty() {
            continue;
        }
        let name = name.as_str()?;
        let session = &preflight["runtime_session"];
        let mut runtime =
            DiscoveryFs::lower(Text::py_strip(&scalar(present(&session["runtime"]), "")?))?;
        if runtime == "agy" {
            runtime = "antigravity".into();
        }
        let sid_raw = scalar(present(&session["session_id"]), "")?;
        let sid = Text::py_strip(&sid_raw);
        let spill = match runtime.as_str() {
            "" => String::new(),
            "codex" | "antigravity" if !sid.is_empty() => {
                let digest = format!("{:x}", Sha256::digest(sid.as_bytes()));
                format!("run_{}", &digest[..24])
            }
            _ => sid.to_owned(),
        };
        let work = &preflight["work"];
        let resume = generation(
            present(&reg["resume_generation"]).or_else(|| present(&session["resume_generation"])),
        )?;
        let previous = scalar(present(&work["previous_action"]), "")?;
        let continuation = resume > 0 || !Text::py_strip(&previous).is_empty();
        let route = &preflight["route"];
        let argv = &preflight["route_command"]["command"];
        let mut candidates = vec![
            &reg["command"],
            &route["command"],
            &route["workflow_command"],
        ];
        if argv.get(2).and_then(Value::as_str) == Some("route") {
            if let Some(word) = argv.get(3) {
                candidates.push(word);
            }
        }
        let route = candidates
            .into_iter()
            .filter_map(Value::as_str)
            .find_map(route_token)
            .unwrap_or("unknown");
        let state = scalar(present(&reg["state"]), "unknown")?;
        let settled = if matches!(state.as_str(), "completed" | "cancelled") {
            utc(&scalar(present(&reg["updated_at"]), "")?)?
        } else {
            String::new()
        };
        let model = scalar(present(&session["model"]), "")?;
        let effort = scalar(present(&session["reasoning_effort"]), "")?;
        runs.push(json!({
            "run_id": name, "work_id": scalar(present(&work["id"]), name)?,
            "runtime": runtime, "session_id": sid, "spill_run_id": spill,
            "stamped_model": Text::py_strip(&model), "stamped_effort": DiscoveryFs::lower(Text::py_strip(&effort))?,
            "route": route, "state": state, "same_work_mode": if continuation {"continuation"} else {"fresh"},
            "resume_generation": resume, "required_docs_count": docs.as_u64()?, "reused_gate_count": gates.as_u64()?,
            "started_at": started, "settled_at": settled,
        }));
    }
    Some(json!({"runs": runs}))
}
