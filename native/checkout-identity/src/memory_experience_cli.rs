//! owner: offline experience evaluator launcher; allowed imports: existing
//! fixture/record/report owners, source and encoding guard, local date and hash;
//! forbidden imports: stores, providers or writes. Callers/tests: stable alias
//! and Python-free CLI parity, with original argv retained on fallback.
use super::{
    experience::ExperienceMetrics, experience_fixture::ExperienceFixture,
    experience_records::ExperienceRecords,
};
use crate::{
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
    path::{Path, PathBuf},
};

const ENTRY: &str = "experience-eval";
const DEFAULT_FIXTURE: &str = "tests/fixtures/project-memory-experience-cases.json";
const ENGINE: &str = "scripts/agent_project_memory.py";
const MEASUREMENT: &str = "rendered retrieval only; listing cases and applicability judgments are excluded from retrieval metrics";

pub(crate) struct ExperienceCli;

impl ExperienceCli {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(output) = Self::report(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        let mut stdout = io::stdout().lock();
        i32::from(
            stdout
                .write_all(output.as_bytes())
                .and_then(|()| stdout.flush())
                .is_err(),
        )
    }

    fn report(launcher: &OsString, args: &[OsString]) -> Option<String> {
        if !PythonEncoding::utf8() {
            return None;
        }
        let root = CallbackGuard::root(launcher, ENTRY)?;
        let fixture_path = fixture_path(&root, args)?;
        // A conservative digit limit allows exact fallback for larger inputs.
        let fixture = ExperienceFixture::load(fixture_path.as_os_str(), 640)?.ok()?;
        if !portable_text(&fixture) {
            return None;
        }
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
            "fixture": provenance(&fixture_path)?,
        });
        let mut output = OverheadReportText::json(&result)?;
        output.push('\n');
        Some(output)
    }
}

fn fixture_path(root: &Path, args: &[OsString]) -> Option<PathBuf> {
    match args {
        [] => Some(root.join(DEFAULT_FIXTURE)),
        [flag, path] if flag == "--fixture" && !path.to_str()?.starts_with('-') => {
            Some(PathBuf::from(path))
        }
        [joined] => Some(PathBuf::from(joined.to_str()?.strip_prefix("--fixture=")?)),
        _ => None, // Historical engines and unproven argparse forms go through Python.
    }
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
