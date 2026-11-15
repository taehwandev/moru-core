//! owner: BehaviorReview offline journal export; allowed imports: std, serde,
//! PythonJson and BehaviorTrace; forbidden imports: providers, child processes,
//! workflow writes and Python fallback; callers/tests: launcher private export,
//! behavior_review_tests and immutable Python CLI oracle; verification: local IO,
//! privacy, byte output, invalid records and relocated empty-PATH checks.
use crate::{
    behavior_trace::BehaviorTrace,
    python_json::{ParseOutcome, PythonJson, Value},
};
use serde_json::json;
use std::{
    ffi::OsString,
    fs::File,
    io::{self, Read, Write},
};

const MAX_BYTES: u64 = 4 * 1024 * 1024;
const FAILURE: &str =
    "Observed trace export failed; inspect the local record and native candidate.\n";

pub(crate) struct BehaviorReview;
enum Failure {
    Invalid,
    Unsupported,
}

impl BehaviorReview {
    pub(crate) fn run(args: &[OsString]) -> i32 {
        match Self::export(args) {
            Ok(value) => {
                let mut output = python_spacing(&value);
                output.push(b'\n');
                if io::stdout().lock().write_all(&output).is_ok() {
                    0
                } else {
                    Self::failed()
                }
            }
            Err(Failure::Unsupported) => 78,
            Err(Failure::Invalid) => Self::failed(),
        }
    }

    fn failed() -> i32 {
        let _ = io::stderr().lock().write_all(FAILURE.as_bytes());
        1
    }

    fn export(args: &[OsString]) -> Result<serde_json::Value, Failure> {
        if args.len() != 5 {
            return Err(Failure::Invalid);
        }
        if args[4] != option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS").unwrap_or("0") {
            return Err(Failure::Unsupported);
        }
        let mut raw = Vec::new();
        File::open(&args[1])
            .map_err(|_| Failure::Invalid)?
            .take(MAX_BYTES + 1)
            .read_to_end(&mut raw)
            .map_err(|_| Failure::Invalid)?;
        if raw.len() as u64 > MAX_BYTES {
            return Err(Failure::Invalid);
        }
        let text = std::str::from_utf8(&raw).map_err(|_| Failure::Unsupported)?;
        // Python json.loads(bytes) accepts a UTF8 BOM and detects UTF16/32.
        if text.contains('\0') {
            return Err(Failure::Unsupported);
        }
        let text = text.strip_prefix('\u{feff}').unwrap_or(text);
        let journal = match PythonJson::parse_outcome(text) {
            ParseOutcome::Value(value) => value,
            ParseOutcome::Unsupported => return Err(Failure::Unsupported),
            ParseOutcome::Invalid => return Err(Failure::Invalid),
        };
        let provider = args[2].to_str().ok_or(Failure::Invalid)?;
        let case_id = args[3].to_str().ok_or(Failure::Invalid)?;
        Self::normalize(&journal, provider, case_id)
    }

    fn normalize(
        journal: &Value,
        provider: &str,
        case_id: &str,
    ) -> Result<serde_json::Value, Failure> {
        let object = journal.as_object().ok_or(Failure::Invalid)?;
        if object.get("phase").and_then(Value::as_str) != Some("finished")
            || !object.get("runtime_path").is_some_and(PythonJson::truthy)
            || !object.get("runtime_digest").is_some_and(PythonJson::truthy)
        {
            return Err(Failure::Invalid);
        }
        let events = object
            .get("events")
            .and_then(Value::as_array)
            .ok_or(Failure::Invalid)?;
        // Every successful reference output has these same bounded ASCII fields.
        // Rejecting other types here cannot turn a normalizer failure into success.
        let last = events
            .last()
            .and_then(Value::as_object)
            .ok_or(Failure::Invalid)?;
        if last.get("event_type").and_then(Value::as_str) != Some("review.finished")
            || last.get("status").and_then(Value::as_str).is_none()
            || last.get("status").and_then(Value::as_str)
                != object.get("status").and_then(Value::as_str)
        {
            return Err(Failure::Invalid);
        }
        let mut output = Vec::new();
        for event in events {
            let event = event.as_object().ok_or(Failure::Invalid)?;
            if event
                .iter()
                .any(|(key, _)| key != "event_type" && key != "status")
            {
                return Err(Failure::Invalid);
            }
            let kind = event
                .get("event_type")
                .and_then(Value::as_str)
                .ok_or(Failure::Invalid)?;
            let mut row = json!({"event_type": kind});
            if let Some(status) = event.get("status") {
                row["status"] = json!(status.as_str().ok_or(Failure::Invalid)?);
            }
            output.push(row);
        }
        BehaviorTrace::normalize(&json!({"schema_version": 1, "provider": provider,
            "case_id": case_id, "events": output}))
        .map_err(|_| Failure::Invalid)
    }
}

// The normalizer guarantees ASCII strings. Preserve its key order and use the
// public Python CLI's json.dumps separators without another subprocess.
fn python_spacing(value: &serde_json::Value) -> Vec<u8> {
    let mut output = Vec::new();
    let (mut quoted, mut escaped) = (false, false);
    for byte in value.to_string().bytes() {
        output.push(byte);
        if escaped {
            escaped = false;
        } else if quoted && byte == b'\\' {
            escaped = true;
        } else if byte == b'"' {
            quoted = !quoted;
        } else if !quoted && matches!(byte, b',' | b':') {
            output.push(b' ');
        }
    }
    output
}

#[cfg(test)]
#[path = "behavior_review_tests.rs"]
mod tests;
