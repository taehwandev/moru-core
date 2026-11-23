//! owner: offline experience evaluator launcher; allowed imports: existing
//! fixture/record/report owners, source and encoding guard, local date and hash;
//! forbidden imports: stores, providers or writes. Callers/tests: stable alias
//! and Python-free CLI parity, with original argv retained on fallback.
use super::{
    experience::ExperienceMetrics, experience_fixture::ExperienceFixture,
    experience_records::ExperienceRecords,
};
use crate::{
    argparse_help::ArgparseHelp,
    memory_terms::MemoryTerms,
    overhead_report_text::OverheadReportText,
    pretool_guard::CallbackGuard,
    python_encoding::PythonEncoding,
    python_input_file::{FileRead, PythonInputFile},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    io::{self, Write},
    path::{Component, Path, PathBuf},
};

const ENTRY: &str = "experience-eval";
const PROG: &str = "agent_experience_eval.py";
const USAGE: &[&str] = &["[-h]", "[--engine-root ENGINE_ROOT]", "[--fixture FIXTURE]"];
const DEFAULT_FIXTURE: &str = "tests/fixtures/project-memory-experience-cases.json";
const ENGINE: &str = "scripts/agent_project_memory.py";
const MEASUREMENT: &str = "rendered retrieval only; listing cases and applicability judgments are excluded from retrieval metrics";

pub(crate) struct ExperienceCli;

impl ExperienceCli {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let output = match Self::report(launcher, &args[1..]) {
            Some(Ok(output)) => output,
            Some(Err(error)) => {
                let Some(width) = plain_width() else {
                    crate::exec_python(launcher, args);
                };
                let usage = ArgparseHelp::usage(PROG, USAGE, width);
                let _ = write!(io::stderr().lock(), "{usage}{PROG}: error: {error}\n");
                return 2;
            }
            None => crate::exec_python(launcher, args),
        };
        let mut stdout = io::stdout().lock();
        i32::from(
            stdout
                .write_all(output.as_bytes())
                .and_then(|()| stdout.flush())
                .is_err(),
        )
    }

    fn report(launcher: &OsString, args: &[OsString]) -> Option<Result<String, String>> {
        if !PythonEncoding::utf8() {
            return None;
        }
        let root = CallbackGuard::root(launcher, ENTRY)?;
        if let [arg] = args {
            if matches!(arg.to_str()?, "-h" | "--h" | "--he" | "--hel" | "--help") {
                return plain_help().map(Ok);
            }
        }
        let fixture_path = match fixture_path(&root, args)? {
            Ok(path) => path,
            Err(error) => return Some(Err(error)),
        };
        // A conservative digit limit allows exact fallback for larger inputs.
        let fixture = match ExperienceFixture::decode(fixture_path.as_os_str(), 640, true)? {
            Ok(fixture) => fixture,
            Err(error) => return Some(Err(error)),
        };
        if !portable_text(&fixture) {
            return None;
        }
        if let Err(error) = ExperienceFixture::validate(&fixture) {
            return Some(Err(error));
        }
        Self::render(&root, &fixture_path, &fixture).map(Ok)
    }

    fn render(root: &Path, fixture_path: &Path, fixture: &Value) -> Option<String> {
        let today = local_date()?;
        let prepared = ExperienceRecords::evaluate(&json!({
            "today": today, "records": fixture.get("records")?,
        }))?;
        let report = ExperienceMetrics::recall(&json!({
            "today": today, "unicode": MemoryTerms::version(),
            "records": prepared.get("records")?, "cases": fixture.get("cases")?,
            "limits": {
                "items": env!("MORU_EXPERIENCE_MAX_RECALL_ITEMS").parse::<u64>().ok()?,
                "chars": env!("MORU_EXPERIENCE_MAX_RECALL_CHARS").parse::<u64>().ok()?,
                "previous": env!("MORU_EXPERIENCE_MAX_PREVIOUS_CHARS").parse::<u64>().ok()?,
            },
        }))?;
        if local_date()? != today {
            return None;
        }
        let mut result = json!({
            "schema_version": 1, "synthetic": true, "evaluation_date": today,
            "measurement": MEASUREMENT,
        });
        result.as_object_mut()?.extend(report.as_object()?.clone());
        result["inputs"] = json!({
            "engine": provenance(&root.join(ENGINE))?,
            "fixture": provenance(fixture_path)?,
        });
        let mut output = OverheadReportText::json(&result)?;
        output.push('\n');
        Some(output)
    }
}

fn fixture_path(root: &Path, args: &[OsString]) -> Option<Result<PathBuf, String>> {
    let mut words = args.iter();
    let (mut fixture, mut engine) = (None, None);
    while let Some(raw) = words.next() {
        let raw = raw.to_str()?;
        let (flag, inline) = raw
            .split_once('=')
            .map_or((raw, None), |(flag, text)| (flag, Some(text)));
        let (name, destination) = match flag {
            flag if flag.len() > 2 && "--fixture".starts_with(flag) => ("--fixture", &mut fixture),
            flag if flag.len() > 2 && "--engine-root".starts_with(flag) => {
                ("--engine-root", &mut engine)
            }
            _ => return None, // Unproven ordering and diagnostics stay with argparse.
        };
        let path = match inline {
            Some(path) => path,
            None => {
                let Some(value) = words.next() else {
                    return Some(Err(format!("argument {name}: expected one argument")));
                };
                value.to_str().filter(|word| !word.starts_with('-'))?
            }
        };
        if path.starts_with("//") {
            return None;
        }
        // Match pathlib's lexical spelling before opening or reporting a path.
        let normalized: PathBuf = Path::new(path)
            .components()
            .filter(|part| *part != Component::CurDir)
            .collect();
        *destination = Some(if normalized.as_os_str().is_empty() {
            ".".into()
        } else {
            normalized
        });
    }
    if let Some(engine) = engine {
        if engine.canonicalize().ok()? != root.join("scripts").canonicalize().ok()? {
            return None;
        }
    }
    Some(Ok(fixture.unwrap_or_else(|| root.join(DEFAULT_FIXTURE))))
}

fn plain_width() -> Option<usize> {
    if std::env::var_os("FORCE_COLOR").is_some()
        || unsafe { libc::isatty(1) != 0 || libc::isatty(2) != 0 }
    {
        return None;
    }
    let columns = match std::env::var("COLUMNS") {
        Ok(value) if value.is_ascii() => value.trim().parse::<usize>().ok()?,
        Err(std::env::VarError::NotPresent) => 80,
        _ => return None,
    };
    (32..=512).contains(&columns).then(|| columns - 2)
}

fn plain_help() -> Option<String> {
    let width = plain_width()?;
    let description = env!("MORU_EXPERIENCE_DESCRIPTION");
    if description.is_empty() {
        return None;
    }
    Some(ArgparseHelp::help(
        PROG,
        USAGE,
        description,
        env!("MORU_ARGPARSE_OPTIONS_TITLE"),
        &[
            ("-h, --help", "show this help message and exit"),
            ("--engine-root ENGINE_ROOT", ""),
            ("--fixture FIXTURE", ""),
        ],
        width,
    ))
}

fn portable_text(value: &Value) -> bool {
    // The launcher cannot query the runtime interpreter's Unicode database.
    // ASCII and modern Hangul syllables have stable term classification.
    fn text(value: &str) -> bool {
        !value.contains("..")
            && value
                .chars()
                .all(|ch| ch.is_ascii() || ('\u{ac00}'..='\u{d7a3}').contains(&ch))
    }
    match value {
        Value::String(value) => text(value),
        Value::Array(values) => values.iter().all(portable_text),
        Value::Object(values) => values
            .iter()
            .all(|(key, value)| text(key) && portable_text(value)),
        _ => true,
    }
}

fn provenance(path: &Path) -> Option<Value> {
    let resolved = path.canonicalize().ok()?;
    let FileRead::Bytes(bytes) = PythonInputFile::read(path.as_os_str(), 4 * 1024 * 1024, false)?
    else {
        return None;
    };
    Some(json!({"path": resolved.to_str()?, "sha256": format!("{:x}", Sha256::digest(&bytes))}))
}

fn local_date() -> Option<String> {
    let seconds = unsafe { libc::time(std::ptr::null_mut()) };
    if seconds < 0 {
        return None;
    }
    let mut local = std::mem::MaybeUninit::<libc::tm>::uninit();
    // libc converts using the inherited local timezone, as date.today does.
    if unsafe { libc::localtime_r(&seconds, local.as_mut_ptr()) }.is_null() {
        return None;
    }
    let local = unsafe { local.assume_init() };
    let year = local.tm_year.checked_add(1900)?;
    let month = local.tm_mon.checked_add(1)?;
    (1..=9999)
        .contains(&year)
        .then(|| format!("{year:04}-{month:02}-{:02}", local.tm_mday))
}
