//! owner: bounded read-only scan of project path claims.
//! allowed imports: regular-file reads, Python JSON and ISO timestamp parsing.
//! forbidden imports: writes, authority decisions and network.
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
        let modern_iso = input.get("modern_iso").and_then(Value::as_bool) == Some(true);
        let status_json = input.get("status_json").and_then(Value::as_bool);
        let conflict = input.get("conflict").filter(|value| value.is_object());
        let release = input.get("release").filter(|value| value.is_object());
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
            let parsed = Self::parse(&raw, digit_limit, modern_iso)?;
            if let Some((expiry, claim)) = parsed {
                rows.push(json!([name, expiry, raw]));
                if status_json.is_some() || conflict.is_some() || release.is_some() {
                    claims.push(claim);
                    earliest = Some(earliest.map_or(expiry, |previous: f64| previous.min(expiry)));
                }
            } else {
                rows.push(json!([name, null, null]));
            }
        }
        let conflicts = conflict
            .filter(|_| rows.len() == claims.len())
            .and_then(|request| Self::conflicts(&claims, &rows, request))
            .map(|matches| json!({"matches": matches, "earliest": earliest}));
        let conflict_key = if conflict
            .and_then(|request| request.get("started"))
            .and_then(Value::as_str)
            .is_some()
        {
            "arbitration"
        } else {
            "conflicts"
        };
        let release = release
            .filter(|_| rows.len() == claims.len())
            .and_then(|request| Self::release_plan(&claims, &rows, request))
            .map(|plan| json!({"plan": plan, "earliest": earliest}));
        let status = status_json
            .filter(|_| rows.len() == claims.len())
            .and_then(|as_json| Self::status(claims, as_json))
            .map(|output| json!({"output": output, "earliest": earliest}));
        let mut result = json!({"rows": rows, "status": status, "release": release});
        result[conflict_key] = conflicts.unwrap_or(Value::Null);
        Some(result)
    }

    pub(super) fn parse(
        raw: &str,
        digit_limit: usize,
        modern_iso: bool,
    ) -> Option<Option<(f64, Claim)>> {
        let record = match PythonJson::parse_with_diagnostic(raw, Some(digit_limit), None) {
            Ok(Some(record)) => record,
            Err(InputDiagnostic::Syntax(_)) => return Some(None),
            _ => return None,
        };
        let Some(expiry) = record.get("expires").and_then(|value| value.as_str()) else {
            return Some(None);
        };
        if expiry.contains('Z')
            && !(modern_iso
                && expiry
                    .strip_suffix('Z')
                    .is_some_and(|clock| !clock.contains('Z')))
        {
            return None;
        }
        let normalized = modern_iso
            .then(|| Self::normalize_fraction(expiry))
            .flatten();
        let stamp = OverheadStamp::parse(normalized.as_deref().unwrap_or(expiry))??;
        // Naive timestamps depend on the caller's local timezone.
        let ticks = stamp.ticks() - 719163 * 86_400_000_000;
        (stamp.aware() && ticks.unsigned_abs() <= 1 << 53)
            .then_some(Some((ticks as f64 / 1_000_000.0, record)))
    }

    fn normalize_fraction(expiry: &str) -> Option<String> {
        let clock = expiry.get(..19)?;
        let remainder = expiry.get(19..)?.strip_prefix(['.', ','])?;
        let offset = remainder.find(['+', '-', 'Z'])?;
        let (fraction, zone) = remainder.split_at(offset);
        if fraction.is_empty() || !fraction.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        // The shared ISO parser still validates the entire clock and offset.
        let micros = &fraction[..fraction.len().min(6)];
        Some(format!("{clock}.{micros:0<6}{zone}"))
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

    fn conflicts(claims: &[Claim], rows: &[Value], request: &Value) -> Option<Vec<Value>> {
        let paths = request.get("paths")?.as_array()?;
        if paths.len() > 1024 {
            return None;
        }
        let paths = paths
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let holder = request.get("holder")?.as_str()?;
        let started = request.get("started").and_then(Value::as_str);
        let mut matches = Vec::new();
        for (claim, row) in claims.iter().zip(rows) {
            if paths.is_empty() || claim.get("holder").and_then(Claim::as_str) == Some(holder) {
                continue;
            }
            let path = claim.get("path")?.as_str()?;
            if !paths.iter().any(|wanted| Self::overlaps(path, wanted)) {
                continue;
            }
            if let Some(started) = started {
                if !Self::precedes(claim, started, holder)? {
                    continue;
                }
            }
            matches.push(row.get(2)?.clone());
        }
        Some(matches)
    }

    fn precedes(claim: &Claim, started: &str, holder: &str) -> Option<bool> {
        let since = match claim.get("since") {
            Some(value) => value.as_str()?,
            None => "",
        };
        match since.cmp(started) {
            std::cmp::Ordering::Less => Some(true),
            std::cmp::Ordering::Greater => Some(false),
            std::cmp::Ordering::Equal => {
                let owner = match claim.get("holder") {
                    Some(value) => value.as_str()?,
                    None => "",
                };
                Some(owner < holder)
            }
        }
    }

    fn overlaps(first: &str, second: &str) -> bool {
        let descendant = |path: &str, parent: &str| {
            path.strip_prefix(parent)
                .is_some_and(|tail| tail.starts_with('/'))
        };
        first == "."
            || second == "."
            || first == second
            || descendant(first, second)
            || descendant(second, first)
    }

    fn release_plan(claims: &[Claim], rows: &[Value], request: &Value) -> Option<Value> {
        let holder = request.get("holder")?.as_str()?;
        let paths = match request.get("paths")? {
            Value::Null => None,
            value => {
                let paths = value.as_array()?;
                if paths.len() > 1024 {
                    return None;
                }
                Some(
                    paths
                        .iter()
                        .map(Value::as_str)
                        .collect::<Option<Vec<_>>>()?,
                )
            }
        };
        let mut owned = Vec::new();
        let mut refused = Vec::new();
        for (claim, row) in claims.iter().zip(rows) {
            let mine = claim.get("holder").and_then(Claim::as_str) == Some(holder);
            if paths.is_none() && !mine {
                continue;
            }
            let path = claim.get("path")?.as_str()?;
            if paths.as_ref().is_some_and(|paths| !paths.contains(&path)) {
                continue;
            }
            if mine {
                owned.push(path);
            } else {
                refused.push(row.get(2)?);
            }
        }
        Some(json!({"owned": owned, "refused": refused}))
    }
}
