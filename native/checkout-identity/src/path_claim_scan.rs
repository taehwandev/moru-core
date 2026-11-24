//! owner: bounded read-only scan of project path claims.
//! allowed imports: regular-file reads, Python JSON and ISO timestamp parsing.
//! forbidden imports: writes, claim ownership decisions and network.
//! callers/tests: path_claims.active_claims; test_path_claims parity.
//! verification: filename order, original JSON values and expiry conversion.
use crate::{
    callback_state::LocalState,
    overhead_stamp::OverheadStamp,
    python_json::{InputDiagnostic, PythonJson, Value as Claim},
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
        let status_json = input.get("status_json").and_then(Value::as_bool);
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
        let mut claims = Vec::new();
        let mut earliest = None;
        let mut bytes = 0;
        for name in names {
            let raw = LocalState::read(&dir.join(&name), 64 * 1024)?;
            bytes += raw.len();
            if bytes > 128 * 1024 {
                return None;
            }
            let parsed = Self::parse(&raw, digit_limit)?;
            if let Some((expiry, claim)) = parsed {
                rows.push(json!([name, expiry, raw]));
                if status_json.is_some() {
                    claims.push(claim);
                    earliest = Some(earliest.map_or(expiry, |previous: f64| previous.min(expiry)));
                }
            } else {
                rows.push(json!([name, null, null]));
            }
        }
        let status = status_json
            .filter(|_| rows.len() == claims.len())
            .and_then(|as_json| Self::status(claims, as_json))
            .map(|output| json!({"output": output, "earliest": earliest}));
        Some(json!({"rows": rows, "status": status}))
    }

    fn parse(raw: &str, digit_limit: usize) -> Option<Option<(f64, Claim)>> {
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
            .then_some(Some((ticks as f64 / 1_000_000.0, record)))
    }

    fn status(claims: Vec<Claim>, as_json: bool) -> Option<String> {
        let mut claims = claims
            .into_iter()
            .map(|claim| Some((claim.get("path")?.as_str()?.to_owned(), claim)))
            .collect::<Option<Vec<_>>>()?;
        // Match Python's stable order for distinct records with the same path.
        claims.sort_by(|a, b| a.0.cmp(&b.0));
        if as_json {
            let value = Claim::Array(claims.into_iter().map(|(_, claim)| claim).collect());
            return PythonJson::render(&value, true, true);
        }
        if claims.is_empty() {
            return Some("no active claims".into());
        }
        let lines = claims
            .into_iter()
            .map(|(path, claim)| {
                let field = |key| match claim.get(key) {
                    None | Some(Claim::Null) => Some("None"),
                    Some(value) => value.as_str(),
                };
                Some(format!(
                    "held by {} since {}: {path} (expires {})",
                    field("holder")?,
                    field("since")?,
                    field("expires")?
                ))
            })
            .collect::<Option<Vec<_>>>()?;
        Some(lines.join("\n"))
    }
}
