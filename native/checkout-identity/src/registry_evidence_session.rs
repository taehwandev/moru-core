//! owner: session and resume-generation validation for canonical run evidence;
//! allowed imports: canonical candidates, bounded state reads, Python whitespace and JSON;
//! forbidden imports: owner selection, registry mutation and worker admission;
//! callers/tests: private registry probe and native registry/session parity;
//! verification: exact session, aliases, generation defaults and compatibility replay.
use super::RegistryRead;
use crate::{callback_state::LocalState, python_text::PythonText};
use serde_json::{json, Value};

impl RegistryRead {
    pub(super) fn evidence_session_matches(payload: &Value) -> Option<Value> {
        if payload.as_object()?.len() != 5 {
            return None;
        }
        let expected_runtime = runtime_name(payload.get("runtime"))?;
        let session = payload.get("session")?.as_str()?;
        let generations = payload.get("generations")?.as_array()?;
        if expected_runtime.is_empty()
            || session.is_empty()
            || generations.len() != payload.get("claims")?.as_array()?.len()
        {
            return None;
        }
        let mut remaining = 8 * 1024 * 1024;
        let mut matched = Vec::new();
        for (path, index) in Self::canonical_evidence_paths(payload)? {
            let generation = generations[index].as_i64()?;
            let raw = LocalState::read(&path, remaining)?;
            remaining -= raw.len() as u64;
            let evidence: Value = serde_json::from_str(&raw).ok()?;
            if binding_matches(&evidence, &expected_runtime, session, generation)? {
                matched.push(index);
            }
        }
        Some(json!(matched))
    }
}

fn binding_matches(
    evidence: &Value,
    runtime: &str,
    session: &str,
    generation: i64,
) -> Option<bool> {
    let Some(bound) = evidence.get("runtime_session").and_then(Value::as_object) else {
        return Some(false);
    };
    if bound.get("session_id").and_then(Value::as_str) != Some(session) {
        return Some(false);
    }
    let bound_runtime = runtime_name(bound.get("runtime"))?;
    if bound_runtime != runtime && bound_runtime != "cli" && runtime != "cli" {
        return Some(false);
    }
    Some(match bound.get("resume_generation") {
        None => generation == 0,
        Some(Value::Number(value)) => value.as_i64()? == generation,
        Some(Value::Bool(value)) => i64::from(*value) == generation,
        _ => false,
    })
}

fn runtime_name(value: Option<&Value>) -> Option<String> {
    let name = match value {
        None | Some(Value::Null) => "",
        Some(value) => value.as_str()?.trim_matches(PythonText::whitespace),
    };
    if !name.is_ascii() {
        return None;
    }
    let name = name.to_ascii_lowercase();
    Some(if name == "agy" {
        "antigravity".into()
    } else {
        name
    })
}
