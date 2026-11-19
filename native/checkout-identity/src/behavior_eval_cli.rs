//! owner: offline behavior evaluator CLI; allowed imports: grader owners, std IO and JSON.
//! forbidden imports: providers, subprocesses, mutations or runtime context.
//! callers/tests: native launcher and Python CLI oracle; verification: output bytes and exit codes.
use crate::{
    behavior_eval::BehaviorEval, behavior_eval_artifact::BehaviorEvalArtifacts,
    behavior_eval_input::BehaviorEvalInput, python_json::PythonJson, python_text::PythonText,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fmt::Write as _,
    fs::OpenOptions,
    io::{self, Read, Write as _},
    os::unix::fs::OpenOptionsExt,
};

const MAX_JSON_BYTES: u64 = 4 * 1024 * 1024;
const DECLINED: i32 = 78;

pub(crate) struct BehaviorEvalCli;

struct Arguments {
    cases: String,
    traces: String,
    artifact_root: String,
    providers: Vec<String>,
}

impl BehaviorEvalCli {
    pub(crate) fn run(args: &[OsString]) -> i32 {
        let Some(args) = Self::arguments(args) else {
            return DECLINED;
        };
        match Self::evaluate(&args) {
            Some(Ok(report)) => {
                let code = i32::from(report["failed"].as_u64() != Some(0));
                let output = Self::encode(&report);
                if io::stdout().lock().write_all(output.as_bytes()).is_ok() {
                    code
                } else {
                    1
                }
            }
            Some(Err(error)) => {
                let _ = writeln!(io::stderr().lock(), "error: {error}");
                2
            }
            None => DECLINED,
        }
    }

    fn arguments(args: &[OsString]) -> Option<Arguments> {
        let words = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()?;
        let mut words = words.into_iter().peekable();
        let (mut cases, mut traces, mut root, mut providers) = (None, None, None, None);
        while let Some(raw) = words.next() {
            let (flag, inline) = raw
                .split_once('=')
                .map_or((raw, None), |(k, v)| (k, Some(v)));
            let next_value = |arg: &&str| !arg.starts_with('-');
            let slot = match flag {
                "--cases" => &mut cases,
                "--traces" => &mut traces,
                "--artifact-root" => &mut root,
                "--providers" => {
                    let mut values = Vec::new();
                    if let Some(value) = inline {
                        values.push(value.to_owned());
                    } else {
                        while let Some(value) = words.next_if(next_value) {
                            values.push(value.to_owned());
                        }
                        if values.is_empty() {
                            return None;
                        }
                    }
                    providers = Some(values);
                    continue;
                }
                _ => return None,
            };
            let value = inline.or_else(|| words.next_if(next_value))?;
            *slot = Some(value.to_owned());
        }
        Some(Arguments {
            cases: cases?,
            traces: traces?,
            artifact_root: root?,
            providers: providers
                .unwrap_or_else(|| BehaviorEvalInput::PROVIDERS.map(str::to_owned).to_vec()),
        })
    }

    fn evaluate(args: &Arguments) -> Option<Result<Value, String>> {
        let run = || -> Result<Option<Value>, String> {
            if args
                .providers
                .iter()
                .flat_map(|value| value.split(','))
                .any(|token| token.trim_matches(PythonText::whitespace).is_empty())
            {
                return Err("empty provider token in --providers".into());
            }
            let Some(cases_doc) = Self::read_json(&args.cases)? else {
                return Ok(None);
            };
            let Some(runs_doc) = Self::read_json(&args.traces)? else {
                return Ok(None);
            };
            let providers = BehaviorEvalInput::providers(&args.providers)?;
            let cases = BehaviorEvalInput::cases(&cases_doc)?;
            let runs = BehaviorEvalInput::runs(&runs_doc, &cases)?;
            let files = BehaviorEvalArtifacts::open(&args.artifact_root)?;
            let mut results = Vec::new();
            let mut passed = 0;
            for provider in providers {
                for case in &cases {
                    let Some(id) = case["id"].as_str() else {
                        return Ok(None);
                    };
                    let events = runs.get(&(provider, id)).copied();
                    let Some(mut failures) = BehaviorEval::trace_failures(case, events) else {
                        return Ok(None);
                    };
                    if events.is_some() {
                        let Some(artifacts) = case["artifacts"].as_object() else {
                            return Ok(None);
                        };
                        for (path, expected) in artifacts {
                            let mut prefix = path.chars();
                            if prefix.next().is_some_and(|ch| !ch.is_ascii())
                                && prefix.next() == Some(':')
                            {
                                // Unicode category differences affect the Python drive test.
                                return Ok(None);
                            }
                            let Some(expected) = expected.as_str() else {
                                return Ok(None);
                            };
                            failures.extend(files.failure(provider, id, path, expected));
                        }
                    }
                    let ok = failures.is_empty();
                    passed += usize::from(ok);
                    results.push(
                        json!({"provider":provider,"case_id":id,"passed":ok,"failures":failures}),
                    );
                }
            }
            Ok(Some(
                json!({"total":results.len(),"passed":passed,"failed":results.len()-passed,"results":results}),
            ))
        };
        run().transpose()
    }

    fn read_json(path: &str) -> Result<Option<Value>, String> {
        let bad_input = |error: io::Error| {
            let detail = error.to_string();
            match error.raw_os_error() {
                Some(code) => format!(
                    "invalid JSON input {path}: [Errno {code}] {}: {}",
                    detail.split(" (os error ").next().unwrap_or(&detail),
                    PythonText::repr(path)
                ),
                None => format!("invalid JSON input {path}: {detail}"),
            }
        };
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(path)
            .map_err(bad_input)?;
        if !file.metadata().map_err(bad_input)?.is_file() {
            return Ok(None);
        }
        let mut bytes = Vec::new();
        file.take(MAX_JSON_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(bad_input)?;
        if bytes.len() as u64 > MAX_JSON_BYTES {
            return Err(format!("input too large: {path}"));
        }
        let Ok(raw) = std::str::from_utf8(&bytes) else {
            return Ok(None);
        };
        if let Ok(value) = serde_json::from_str::<Value>(raw) {
            return Ok(Some(value));
        }
        match PythonJson::error(raw) {
            Some(detail) => Err(format!("invalid JSON input {path}: {detail}")),
            None => Ok(None),
        }
    }

    fn encode(value: &Value) -> String {
        let json = serde_json::to_string_pretty(value).expect("validated diagnostic report");
        let mut output = String::new();
        for ch in json.chars() {
            if ch.is_ascii() && ch != '\u{7f}' {
                output.push(ch);
            } else {
                for unit in ch.encode_utf16(&mut [0; 2]) {
                    let _ = write!(output, "\\u{unit:04x}");
                }
            }
        }
        output.push('\n');
        output
    }
}
