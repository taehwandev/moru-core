//! owner: bounded read-only scan of project path claims.
//! allowed imports: regular-file reads, Python JSON and ISO timestamp parsing.
//! forbidden imports: writes, claim ownership decisions and network.
//! callers/tests: path_claims.active_claims; test_path_claims parity.
//! verification: filename order, original JSON values and expiry conversion.
use crate::{
    callback_state::LocalState,
    overhead_stamp::OverheadStamp,
    python_json::{InputDiagnostic, PythonJson},
};
use serde_json::{json, Value};
use std::{fs, path::Path};

pub(super) struct PathClaimScan;

impl PathClaimScan {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let project = Path::new(input.get("project")?.as_str()?);
        if !project.is_absolute() {
            return None;
        }
        let digit_limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let dir = project.join(".moru/claims");
        LocalState::safe_path(project, &dir)?;
        if LocalState::absent_dir(&dir)? {
            return Some(json!({"rows": []}));
        }
        let mut names = Vec::new();
        for (index, entry) in fs::read_dir(&dir).ok()?.enumerate() {
            if index == 1024 {
                return None;
            }
            let entry = entry.ok()?;
            let name = entry.file_name().into_string().ok()?;
            if name.ends_with(".json") {
                names.push(name);
            }
        }
        names.sort_unstable();
        let mut rows = Vec::new();
        let mut bytes = 0;
        for name in names {
            let raw = LocalState::read(&dir.join(&name), 64 * 1024)?;
            bytes += raw.len();
            if bytes > 128 * 1024 {
                return None;
            }
            let expiry = Self::expiry(&raw, digit_limit)?;
            rows.push(json!([name, expiry, expiry.map(|_| raw)]));
        }
        Some(json!({"rows": rows}))
    }

    fn expiry(raw: &str, digit_limit: usize) -> Option<Option<f64>> {
        let record = match PythonJson::parse_with_diagnostic(raw, Some(digit_limit), None) {
            Ok(Some(record)) => record,
            Err(InputDiagnostic::Syntax(_)) => return Some(None),
            _ => return None,
        };
        let Some(expiry) = record.get("expires").and_then(|value| value.as_str()) else {
            return Some(None);
        };
        // Z and out-of-profile dates use the caller's Python version. Naive
        // timestamps depend on its local timezone, unlike stored UTC claims.
        if expiry.contains('Z') {
            return None;
        }
        let stamp = OverheadStamp::parse(expiry)??;
        let ticks = stamp.ticks() - 719163 * 86_400_000_000;
        (stamp.aware() && ticks.unsigned_abs() <= 1 << 53)
            .then_some(Some(ticks as f64 / 1_000_000.0))
    }
}
