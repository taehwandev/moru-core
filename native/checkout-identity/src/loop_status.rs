//! owner: explicit-run loop status; allowed imports: local bounded reads, JSON and source guard;
//! forbidden imports: writes, locking, verifier or model execution, and run ownership claims;
//! callers/tests: stable loop CLI and persisted-state parity fixtures.
#[path = "loop_status_contract.rs"]
mod contract;
use crate::{
    callback_state::LocalState,
    pretool_guard::CallbackGuard,
    python_json::{Number, Object, PythonJson, Value},
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
        let run = project.join(".moru").join("runs").join(run_id);
        let state = run.join("loop.json");
        LocalState::safe_path(&project, &state)?;
        LocalState::safe_path(&run, &run.join("preflight.json"))?;
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

    fn arguments(args: &[OsString]) -> Option<(PathBuf, &str)> {
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
        let run_id = run_id?;
        if run_id.len() != 32
            || !run_id
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return None;
        }
        Some((project.or_else(|| env::current_dir().ok())?, run_id))
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
