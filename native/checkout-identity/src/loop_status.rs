//! owner: loop status; allowed imports: bounded reads, session selection, JSON and source guard;
//! forbidden imports: writes, verifier or model execution, and run ownership claims;
//! callers/tests: stable loop CLI, caller-owned persisted encoding and parity fixtures.
#[path = "loop_status_contract.rs"]
mod contract;
use crate::{
    callback_state::LocalState,
    next_process::session::NextSession,
    pretool_guard::CallbackGuard,
    python_json::{Number, Object, PythonJson, Value},
    runtime_identity::RuntimeIdentity,
};
use std::{
    env,
    ffi::OsString,
    io::{self, Write},
    path::PathBuf,
};

pub(crate) struct LoopStatus;
impl LoopStatus {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        let (project, run_id) = Self::arguments(args)?;
        CallbackGuard::root(launcher, "loop")?;
        let project = project.canonicalize().ok()?;
        let evidence = if let Some(run_id) = run_id {
            project
                .join(".moru")
                .join("runs")
                .join(run_id)
                .join("preflight.json")
        } else {
            match RuntimeIdentity::current()? {
                Some((runtime, id)) => NextSession::discover_for(&project, runtime, &id)??,
                None => NextSession::discover_owned(&project)??,
            }
        };
        if evidence.file_name()?.to_str()? != "preflight.json" {
            return None;
        }
        let run = evidence.parent()?;
        let run_id = run.file_name()?.to_str()?;
        if !Self::valid_run_id(run_id) {
            return None;
        }
        let state = run.join("loop.json");
        LocalState::safe_path(&project, &state)?;
        LocalState::safe_path(run, &evidence)?;
        const LIMIT: u64 = 2 * 1024 * 1024;
        let state = PythonJson::parse(&LocalState::read(&state, LIMIT)?)?;
        contract::validate(&state, run_id)?;
        let snapshot = Self::strict_sorted(&state)?;
        let mut output = PythonJson::render(&snapshot, false, true)?;
        if output.len() as u64 > LIMIT {
            return None;
        }
        output.push('\n');
        if io::stdout().lock().write_all(output.as_bytes()).is_err() {
            return Some(2);
        }
        Some(if state["status"].as_str() == Some("exhausted") {
            4
        } else {
            0
        })
    }

    pub(crate) fn encode_persisted(bytes: &[u8]) -> Option<String> {
        let state = PythonJson::parse(std::str::from_utf8(bytes).ok()?)?;
        let run_id = state.get("run_id")?.as_str()?;
        if !Self::valid_run_id(run_id) {
            return None;
        }
        contract::validate(&state, run_id)?;
        let mut encoded = PythonJson::render(&Self::strict_sorted(&state)?, true, true)?;
        if encoded.len() >= 2 * 1024 * 1024 {
            return None;
        }
        encoded.push('\n');
        Some(encoded)
    }

    fn arguments(args: &[OsString]) -> Option<(PathBuf, Option<&str>)> {
        let (action, mut tail) = args.split_first()?;
        if action != "status" {
            return None;
        }
        let mut run_id = None;
        let mut project = None;
        while let Some((argument, rest)) = tail.split_first() {
            tail = rest;
            let argument = argument.to_str()?;
            let (name, value) = if let Some(pair) = argument.split_once('=') {
                pair
            } else {
                let (value, rest) = tail.split_first()?;
                tail = rest;
                (argument, value.to_str()?)
            };
            if value.is_empty() || value.starts_with('-') {
                return None;
            }
            match name {
                "--project" => project = Some(PathBuf::from(value)),
                "--run-id" => run_id = Some(value),
                _ => return None,
            }
        }
        // Check before composing the project-local path, then verify the
        // resolved evidence directory as well when the ID is inferred.
        if run_id.is_some_and(|id| !Self::valid_run_id(id)) {
            return None;
        }
        Some((project.or_else(|| env::current_dir().ok())?, run_id))
    }

    fn valid_run_id(id: &str) -> bool {
        id.len() == 32
            && id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    }

    fn strict_sorted(value: &Value) -> Option<Value> {
        match value {
            Value::Number(Number::Float(value)) if !value.is_finite() => None,
            Value::Object(object) => {
                let mut entries: Vec<_> = object.iter().collect();
                entries.sort_unstable_by(|left, right| left.0.cmp(right.0));
                let mut sorted = Object::new();
                for (key, value) in entries {
                    sorted.insert(key.clone(), Self::strict_sorted(value)?);
                }
                Some(Value::Object(sorted))
            }
            Value::Array(values) => Some(Value::Array(
                values
                    .iter()
                    .map(Self::strict_sorted)
                    .collect::<Option<_>>()?,
            )),
            other => Some(other.clone()),
        }
    }
}
