//! Owner: guarded public HQ decision launcher and stream delivery.
//! Allowed imports: callback source guard, encoding and the existing CLI.
//! Forbidden imports: report policy, state writes and provider dependencies.
//! Callers/tests: native launcher and HQ decision alias tests.
use super::hq_decision_cli;
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{self, Write},
};

pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
    if CallbackGuard::root(launcher, "agent-hq-report").is_none() || !PythonEncoding::utf8() {
        crate::exec_python(launcher, args);
    }
    let Some(argv) = args[1..]
        .iter()
        .map(|arg| arg.to_str())
        .collect::<Option<Vec<_>>>()
    else {
        crate::exec_python(launcher, args);
    };
    let Some(outcome) = hq_decision_cli::run(&json!({"argv": argv})) else {
        crate::exec_python(launcher, args);
    };
    // The decision owner can already have committed the report. Output errors
    // and malformed receipts must terminate here without replaying the action.
    outcome.ok().and_then(deliver).unwrap_or(1)
}

fn deliver(result: Value) -> Option<i32> {
    let code = i32::try_from(result.get("code")?.as_i64()?).ok()?;
    let stdout = result.get("stdout")?.as_str()?;
    let stderr = result.get("stderr")?.as_str()?;
    io::stdout().lock().write_all(stdout.as_bytes()).ok()?;
    io::stderr().lock().write_all(stderr.as_bytes()).ok()?;
    Some(code)
}
