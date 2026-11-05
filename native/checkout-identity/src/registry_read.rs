//! Owner: prepared read-only registry snapshots and latest-binding projection.
//! Allowed: existing source/lock guards, std and JSON. Forbidden: writes, claims,
//! ownership/session decisions or blocking lock acquisition. Callers/tests:
//! private registry adapter; native registry and runtime-session regressions.
use crate::{callback_state::LocalState, pretool_guard::CallbackGuard};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    ffi::OsString,
    io::{Read, Write},
    path::Path,
};

pub(crate) struct RegistryRead;

impl RegistryRead {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2 || CallbackGuard::root(launcher, "registry-read").is_none() {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        let Some(result) = serde_json::from_slice::<Value>(&bytes)
            .ok()
            .and_then(|payload| Self::inspect(args[1].to_str()?, &payload))
        else {
            return 125;
        };
        let Ok(mut output) =
            serde_json::to_vec(&json!({"schema_version":1,"result":{"value":result}}))
        else {
            return 125;
        };
        output.push(b'\n');
        if output.len() > 1024 * 1024 {
            return 125;
        }
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }

    fn inspect(operation: &str, payload: &Value) -> Option<Value> {
        if !["active", "bindings", "latest"].contains(&operation) {
            return None;
        }
        let dir = Path::new(payload.get("state_dir")?.as_str()?);
        if !dir.is_absolute() || dir.canonicalize().ok()?.as_path() != dir {
            return None;
        }
        LocalState::safe_path(Path::new("/"), dir)?;
        let _project = LocalState::lock(&dir.join(".state.lock.lock"))?;
        let _registry = LocalState::lock(&dir.join(".run-registry.json.lock"))?;
        let raw = LocalState::read(&dir.join("run-registry.json"), 1024 * 1024)?;
        let data: Value = serde_json::from_str(&raw).ok()?;
        if data.get("schema_version")?.as_u64()? != 1 || !lossless(&data) {
            return None;
        }
        let mut runs = data.get("runs")?.as_array()?.clone();
        for run in &mut runs {
            let row = run.as_object_mut()?;
            row.entry("resume_generation").or_insert(json!(0));
            for name in ["evidence_key", "evidence_name", "run_id", "state"] {
                if row
                    .get(name)
                    .is_some_and(|v| !v.is_null() && !v.is_string())
                {
                    return None;
                }
            }
        }
        if operation == "latest" {
            let key = payload.get("evidence_key")?.as_str()?;
            let legacy = payload.get("legacy_default")?.as_bool()?;
            let name = payload.get("evidence_name")?.as_str()?;
            let found = runs.iter().rev().find(|run| {
                let own = run
                    .get("evidence_key")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !own.is_empty() {
                    own == key
                } else {
                    legacy && run.get("evidence_name").and_then(Value::as_str) == Some(name)
                }
            });
            return Some(
                found
                    .and_then(|run| run.get("run_id"))
                    .and_then(Value::as_str)
                    .filter(|id| !id.is_empty())
                    .map_or(Value::Null, |id| json!(id)),
            );
        }
        let states = payload
            .get("states")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let selected = |run: &Value| {
            run.get("state")
                .and_then(Value::as_str)
                .is_some_and(|state| states.contains(&state))
        };
        if operation == "active" {
            return Some(Value::Array(runs.into_iter().filter(selected).collect()));
        }
        let legacy = payload.get("legacy_key")?.as_str()?;
        let mut indexes = HashMap::new();
        let mut latest: Vec<(String, Value)> = Vec::new();
        for run in runs {
            let mut key = run
                .get("evidence_key")
                .and_then(Value::as_str)
                .unwrap_or("");
            if key.is_empty()
                && run.get("evidence_name").and_then(Value::as_str) == Some("preflight.json")
            {
                key = legacy;
            }
            if key.is_empty() {
                continue;
            }
            if let Some(index) = indexes.get(key).copied() {
                latest[index] = (key.to_owned(), run);
            } else {
                indexes.insert(key.to_owned(), latest.len());
                latest.push((key.to_owned(), run));
            }
        }
        Some(Value::Array(
            latest
                .into_iter()
                .filter(|(_, run)| selected(run))
                .map(|(key, run)| json!([key, run]))
                .collect(),
        ))
    }
}

// Python preserves arbitrary-size integers. Decline float-decoded numbers,
// including oversized integers, rather than silently changing a copied row.
fn lossless(value: &Value) -> bool {
    match value {
        Value::Number(n) => !n.is_f64(),
        Value::Array(rows) => rows.iter().all(lossless),
        Value::Object(row) => row.values().all(lossless),
        _ => true,
    }
}
