//! owner: InputFreshness; allowed imports: read-only preflight, PythonJson, InputCapture;
//! forbidden imports: ledger writes/reuse authority; callers/tests: NextLedger;
//! verification: schema2 valid/stale capture parity, explicit error versus uncertainty handling.
#[path = "next_input_capture.rs"]
mod capture;
use crate::python_json::{Object, ParseOutcome, PythonJson as Py, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};
pub(super) struct InputFreshness;
impl InputFreshness {
    pub fn valid(snapshot: &Object, evidence: &Path) -> Option<bool> {
        let text = match fs::read_to_string(evidence) {
            Ok(text) => text,
            Err(_) => return Some(false),
        };
        let current = match Py::parse_outcome(&text) {
            ParseOutcome::Value(v) => v,
            ParseOutcome::Invalid => return Some(false),
            ParseOutcome::Unsupported => return None,
        };
        let Some(p) = current.as_object() else {
            return Some(false);
        };
        let project = match Self::path(p.get("project")) {
            Some(path) => path,
            None => return Some(false),
        };
        let rules = match Self::path(p.get("rules")) {
            Some(path) => path,
            None => return Some(false),
        };
        if snapshot.get("project").and_then(Value::as_str) != project.to_str()
            || snapshot.get("rules").and_then(Value::as_str) != rules.to_str()
        {
            return Some(false);
        }
        let Some(paths) = snapshot.get("input_paths").and_then(Value::as_array) else {
            return Some(false);
        };
        let Some(paths) = paths
            .iter()
            .map(Value::as_str)
            .map(|v| v.map(str::to_owned))
            .collect::<Option<Vec<_>>>()
        else {
            return Some(false);
        };
        let Some(project_hash) = capture::InputCapture::capture(&project, &paths)? else {
            return Some(false);
        };
        let Some(rules_hash) = capture::InputCapture::capture(&rules, &[])? else {
            return Some(false);
        };
        let Some(states) = snapshot.get("states").and_then(Value::as_object) else {
            return Some(false);
        };
        Some(
            states.len() == 2
                && states.get("project").and_then(Value::as_str) == Some(project_hash.as_str())
                && states.get("rules").and_then(Value::as_str) == Some(rules_hash.as_str()),
        )
    }
    fn path(value: Option<&Value>) -> Option<PathBuf> {
        let raw = value?.as_str()?;
        if raw.contains('\0') {
            return None;
        }
        // pathlib drops redundant separators/dot segments but keeps leading // on POSIX.
        let prefix = if raw.starts_with("//") && !raw.starts_with("///") {
            "//"
        } else if raw.starts_with('/') {
            "/"
        } else {
            ""
        };
        let parts = raw
            .split('/')
            .filter(|part| !part.is_empty() && *part != ".")
            .collect::<Vec<_>>()
            .join("/");
        let path = format!("{prefix}{parts}");
        Some(PathBuf::from(if path.is_empty() { "." } else { &path }))
    }
}
#[cfg(test)]
#[path = "next_input_freshness_tests.rs"]
mod tests;
