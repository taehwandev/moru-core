//! owner: offline behavior evaluator CLI; allowed imports: grader owners, std IO and JSON.
//! forbidden imports: providers, subprocesses, mutations or runtime context.
//! callers/tests: native launcher and Python CLI oracle; verification: output bytes and exit codes.
use crate::{
    behavior_eval::BehaviorEval,
    behavior_eval_artifact::BehaviorEvalArtifacts,
    behavior_eval_input::{BehaviorEvalError, BehaviorEvalInput},
    python_input_file::{FileRead, PythonInputFile},
    python_json::{InputDiagnostic, PythonJson, Value as PythonValue},
    python_text::{PythonText, PythonUtf8},
};
use serde_json::{json, Value};
#[path = "behavior_eval_public_args.rs"]
mod public_args;
use std::{
    ffi::{OsStr, OsString},
    fmt::Write as _,
    io::{self, Write as _},
};

const MAX_JSON_BYTES: u64 = 4 * 1024 * 1024;
const DECLINED: i32 = 78;

pub(crate) struct BehaviorEvalCli;

struct Arguments {
    cases: String,
    traces: String,
    artifact_root: String,
    providers: Vec<String>,
    digit_limit: Option<usize>,
    integer_error_template: Option<String>,
    stable_errors_only: bool,
    matching_unicode: bool,
    modern_trailing_comma: Option<bool>,
}

impl BehaviorEvalCli {
    pub(crate) fn run(args: &[OsString]) -> i32 {
        let normalized;
        let args = if let Some(index) = args.iter().position(|arg| arg == "--public-args") {
            let public = match public_args::BehaviorEvalPublicArgs::normalize(&args[index + 1..]) {
                Ok(Some(public)) => public,
                Ok(None) => return DECLINED,
                Err(error) => return Self::error(&error),
            };
            normalized = args[..index]
                .iter()
                .cloned()
                .chain(public)
                .collect::<Vec<_>>();
            normalized.as_slice()
        } else {
            args
        };
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
            Some(Err(BehaviorEvalError::Reference(_))) if args.stable_errors_only => DECLINED,
            Some(Err(BehaviorEvalError::Unicode(_)))
                if args.stable_errors_only && !args.matching_unicode =>
            {
                DECLINED
            }
            Some(Err(
                BehaviorEvalError::Stable(error)
                | BehaviorEvalError::Unicode(error)
                | BehaviorEvalError::Reference(error),
            )) => Self::error(&error),
            None => DECLINED,
        }
    }

    fn error(error: &str) -> i32 {
        let _ = writeln!(io::stderr().lock(), "error: {error}");
        2
    }

    fn arguments(args: &[OsString]) -> Option<Arguments> {
        let words = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()?;
        let mut words = words.into_iter().peekable();
        let (mut cases, mut traces, mut root, mut providers) = (None, None, None, None);
        let mut digit_limit = None;
        let mut integer_error_template = None;
        let mut stable_errors_only = false;
        let mut matching_unicode = false;
        let mut modern_trailing_comma = None;
        while let Some(raw) = words.next() {
            let (flag, inline) = raw
                .split_once('=')
                .map_or((raw, None), |(k, v)| (k, Some(v)));
            let next_value = |arg: &&str| !arg.starts_with('-');
            let slot = match flag {
                "--cases" => &mut cases,
                "--traces" => &mut traces,
                "--artifact-root" => &mut root,
                "--stable-errors-only" if inline.is_none() => {
                    stable_errors_only = true;
                    continue;
                }
                "--unicode-version" => {
                    let version = inline.or_else(|| words.next_if(next_value))?;
                    matching_unicode = PythonText::matches_unicode_version(version);
                    continue;
                }
                "--json-trailing-comma" => {
                    modern_trailing_comma = match inline.or_else(|| words.next_if(next_value))? {
                        "legacy" => Some(false),
                        "modern" => Some(true),
                        _ => return None,
                    };
                    continue;
                }
                "--int-max-str-digits" => {
                    let limit = inline
                        .or_else(|| words.next_if(next_value))?
                        .parse::<u32>()
                        .ok()?;
                    digit_limit = Some(usize::try_from(limit).ok()?);
                    continue;
                }
                "--json-integer-error" => {
                    let template = inline.or_else(|| words.next_if(next_value))?;
                    if template.len() > 512
                        || !template.bytes().all(|byte| matches!(byte, b' '..=b'~'))
                        || template.matches("{limit}").count() != 1
                        || template.matches("{digits}").count() != 1
                    {
                        return None;
                    }
                    integer_error_template = Some(template.to_owned());
                    continue;
                }
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
            digit_limit,
            integer_error_template,
            stable_errors_only,
            matching_unicode,
            modern_trailing_comma,
            providers: providers
                .unwrap_or_else(|| BehaviorEvalInput::PROVIDERS.map(str::to_owned).to_vec()),
        })
    }

    fn evaluate(args: &Arguments) -> Option<Result<Value, BehaviorEvalError>> {
        let run = || -> Result<Option<Value>, BehaviorEvalError> {
            if args
                .providers
                .iter()
                .flat_map(|value| value.split(','))
                .any(|token| token.trim_matches(PythonText::whitespace).is_empty())
            {
                return Err("empty provider token in --providers".into());
            }
            let Some(cases_doc) = Self::read_json(&args.cases, args)? else {
                return Ok(None);
            };
            let Some(runs_doc) = Self::read_json(&args.traces, args)? else {
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
                        for (path, expected) in artifacts.iter() {
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

    fn read_json(path: &str, args: &Arguments) -> Result<Option<PythonValue>, BehaviorEvalError> {
        let bytes = match PythonInputFile::read(OsStr::new(path), MAX_JSON_BYTES, true) {
            Some(FileRead::Bytes(bytes)) => bytes,
            Some(FileRead::TooLarge) => {
                return Err(BehaviorEvalError::Stable(format!(
                    "input too large: {path}"
                )))
            }
            Some(FileRead::Error(error)) => {
                let detail = format!("invalid JSON input {path}: {error}");
                return Err(if path.is_ascii() {
                    BehaviorEvalError::Stable(detail)
                } else {
                    BehaviorEvalError::Unicode(detail)
                });
            }
            None => return Ok(None),
        };
        let raw = PythonUtf8::decode(&bytes).map_err(|detail| {
            BehaviorEvalError::Stable(format!("invalid JSON input {path}: {detail}"))
        })?;
        match PythonJson::parse_with_diagnostic(raw, args.digit_limit, args.modern_trailing_comma) {
            Ok(value) => Ok(value),
            Err(diagnostic) => match diagnostic {
                InputDiagnostic::Syntax(detail) => {
                    let error = format!("invalid JSON input {path}: {detail}");
                    Err(if args.modern_trailing_comma.is_some() {
                        BehaviorEvalError::Stable(error)
                    } else {
                        BehaviorEvalError::Reference(error)
                    })
                }
                InputDiagnostic::IntegerLimit {
                    limit,
                    digits,
                    builder_text,
                } => {
                    if let Some(template) = &args.integer_error_template {
                        let error = template
                            .replace("{limit}", &limit.to_string())
                            .replace("{digits}", &digits.to_string());
                        Err(BehaviorEvalError::Stable(error))
                    } else if let Some(detail) = builder_text {
                        Err(BehaviorEvalError::Reference(detail))
                    } else {
                        Ok(None)
                    }
                }
            },
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
