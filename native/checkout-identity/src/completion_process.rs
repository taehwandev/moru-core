//! Owner: private bounded completion-policy JSON protocol.
//! Allowed: existing source guard and three completion policy owners, std/JSON.
//! Forbidden: shells, providers, policy/state writes or public authority.
//! Callers/tests: thin completion adapter; native completion and bundle tests.
use crate::{
    completion_progress::Progress, completion_quality::Quality,
    completion_requirements::Requirements, pretool_guard::CallbackGuard,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
};

pub(crate) struct CompletionProcess;

impl CompletionProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2 || CallbackGuard::root(launcher, "completion-probe").is_none() {
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
        let Ok(payload) = serde_json::from_slice::<Value>(&bytes) else {
            return 125;
        };
        let result = match args[1].to_str() {
            Some("quality") => Quality::inspect(&payload),
            Some("requirements") => Requirements::validate(&payload),
            Some("coverage") => Requirements::coverage(&payload),
            Some("progress") => Progress::inspect(&payload),
            _ => None,
        };
        let Some(result) = result else {
            return 125;
        };
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1,"result":result}))
        else {
            return 125;
        };
        output.push(b'\n');
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }
}
