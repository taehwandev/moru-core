//! owner: durable AGY callback input and terminal advisory verdicts;
//! allowed imports: source guard, Python JSON semantics, exact replay and std;
//! forbidden imports: tool execution, state writes, permission or workflow policy;
//! callers/tests: stable launcher agy-hook and generated callback conformance;
//! verification: bytes, no-Python read decisions and complete compatibility replay.
use crate::{
    callback_replay::CallbackReplay,
    pretool_guard::CallbackGuard,
    python_json::{ParseOutcome, PythonJson, Value},
    python_text::PythonText,
};
use std::{
    ffi::OsString,
    io::{self, Read, Write},
    path::Path,
};

const MAX_INPUT: u64 = 128 * 1024;
const ALLOW: &[u8] = b"{\"decision\": \"allow\"}\n";
const EMPTY: &[u8] = b"{}\n";

pub(crate) struct AgyHookProcess;

impl AgyHookProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let [_, event] = args else {
            crate::exec_python(launcher, args)
        };
        let Some(event @ ("pre-tool" | "pre-invocation" | "stop")) = event.to_str() else {
            crate::exec_python(launcher, args)
        };
        if CallbackGuard::root(launcher, "agy-hook").is_none() {
            crate::exec_python(launcher, args)
        }
        let mut stdin = io::stdin().lock();
        let mut prefix = Vec::new();
        let failed = (&mut stdin)
            .take(MAX_INPUT + 1)
            .read_to_end(&mut prefix)
            .is_err();
        let output = if failed {
            Some(fail_open(event))
        } else if prefix.len() as u64 <= MAX_INPUT {
            verdict(event, &prefix)
        } else {
            None
        };
        match output {
            Some(output) => {
                let mut stdout = io::stdout().lock();
                i32::from(
                    stdout
                        .write_all(output)
                        .and_then(|_| stdout.flush())
                        .is_err(),
                )
            }
            None => CallbackReplay::python_reader(launcher, args, prefix.as_slice().chain(stdin)),
        }
    }
}

fn fail_open(event: &str) -> &'static [u8] {
    if event == "pre-tool" {
        ALLOW
    } else {
        EMPTY
    }
}

fn verdict(event: &str, raw: &[u8]) -> Option<&'static [u8]> {
    let text = std::str::from_utf8(raw).ok()?;
    if text.trim_matches(PythonText::whitespace).is_empty() {
        return (event == "pre-tool").then_some(ALLOW);
    }
    match PythonJson::parse_outcome(text) {
        ParseOutcome::Invalid if !PythonJson::integer_conversion_failed(text) => {
            Some(fail_open(event))
        }
        ParseOutcome::Value(payload) if event == "pre-tool" && no_tool_policy(&payload)? => {
            Some(ALLOW)
        }
        _ => None,
    }
}

fn no_tool_policy(payload: &Value) -> Option<bool> {
    let Some(call) = payload.get("toolCall") else {
        return Some(true);
    };
    let name = match call.get("name") {
        Some(value) if PythonJson::truthy(value) => value.as_str()?,
        _ => "",
    };
    match name {
        "run_command" | "write_file" | "edit_file" => Some(false),
        "read_file" => {
            let args = call.get("args").unwrap_or(&Value::Null);
            let path = ["Path", "AbsolutePath"]
                .into_iter()
                .filter_map(|name| args.get(name))
                .find(|value| PythonJson::truthy(value));
            let path = match path {
                Some(value) => value.as_str()?,
                None => "",
            };
            Some(
                Path::new(path)
                    .file_name()
                    .is_none_or(|name| name != "SKILL.md"),
            )
        }
        _ => Some(true),
    }
}
