//! owner: WikimapSearch; allowed imports: source guard, ReadProcess, std, JSON and SHA-256.
//! forbidden imports: shell, index maintenance policy, routing or provider calls.
//! callers/tests: private launcher probe and workflow Wikimap adapter.
//! verification: pinned script, closed search and update arguments and subprocess parity.
use crate::{pretool_guard::CallbackGuard, read_process::status::capture_status};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    fs,
    io::{self, Read},
    os::unix::process::ExitStatusExt,
    path::Path,
    process::Command,
    time::Duration,
};

const VENDOR: &str = "scripts/third_party/wikimap/wikimap.py";
const VENDOR_SHA256: &str = "0322cd07037f33d8f7a42a84ced4ba8a10bc9d3829cc4b0faea4b1a566c4ea4d";
const LIMIT: usize = 1024 * 1024;

pub(crate) struct WikimapSearch;

impl WikimapSearch {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        // The old probe declines the extended argv before running any command.
        let (update, project_results) = match args {
            [_] => (false, false),
            [_, operation] if operation == "update-v1" => (true, false),
            [_, operation] if operation == "search-results-v1" => (false, true),
            _ => return 125,
        };
        let Some(source) = CallbackGuard::root(launcher, "wikimap-search-probe") else {
            return 125;
        };
        let mut bytes = Vec::new();
        if io::stdin()
            .take((LIMIT + 1) as u64)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > LIMIT
        {
            return 125;
        }
        let Some(result) = serde_json::from_slice::<Value>(&bytes)
            .ok()
            .and_then(|packet| Self::execute(&source, &packet, update, project_results))
        else {
            return 125;
        };
        if serde_json::to_writer(io::stdout().lock(), &result).is_ok() {
            0
        } else {
            1
        }
    }

    fn execute(
        source: &Path,
        packet: &Value,
        update: bool,
        project_results: bool,
    ) -> Option<Value> {
        let fields = packet.as_object()?;
        if fields.len() != if update { 1 } else { 3 } {
            return None;
        }
        let root = Path::new(fields.get("root")?.as_str()?);
        if !root.is_absolute() || !root.is_dir() {
            return None;
        }
        let command_args = if update {
            [
                "update",
                "--no-map",
                "--ignore",
                ".moru",
                "--ignore",
                "scripts/.moru",
                "--ignore",
                "scripts/third_party",
            ]
            .into_iter()
            .map(OsString::from)
            .collect()
        } else {
            Self::search_args(root, fields)?
        };
        let script = source.join(VENDOR);
        let metadata = fs::metadata(&script).ok()?;
        if !metadata.is_file()
            || metadata.len() > LIMIT as u64
            || format!("{:x}", Sha256::digest(fs::read(&script).ok()?)) != VENDOR_SHA256
        {
            return None;
        }
        let mut command = Command::new("python3");
        command
            .arg(script)
            .arg("--root")
            .arg(root)
            .args(command_args)
            .current_dir(root);
        let Some((stdout, stderr, status)) =
            capture_status(&mut command, Duration::from_secs(15), None)
                .ok()
                .flatten()
        else {
            return Some(json!({"failed": true}));
        };
        // All post-launch failures are terminal. A declined update is safe to
        // retry only before the vendor has had a chance to touch the index.
        let result = status
            .code()
            .or_else(|| status.signal().map(|signal| -signal))
            .zip(String::from_utf8(stdout).ok())
            .zip(String::from_utf8(stderr).ok());
        Some(match result {
            Some(((code, stdout), stderr)) => {
                if code == 0 && project_results && stdout.len() <= LIMIT {
                    if let Some(projection) = Self::project_results(&stdout) {
                        return Some(json!({"projection": projection}));
                    }
                }
                json!({"code": code, "stdout": stdout, "stderr": stderr})
            }
            None => json!({"failed": true}),
        })
    }

    fn project_results(stdout: &str) -> Option<Value> {
        let payload: Value = serde_json::from_str(stdout).ok()?;
        let payload = payload.as_object()?;
        let mut result = serde_json::Map::new();
        for flag in ["weak", "partial", "fused"] {
            let value = match payload.get(flag) {
                None | Some(Value::Null) => false,
                Some(value) => value.as_bool()?,
            };
            result.insert(flag.to_owned(), json!(value));
        }
        let rows = payload.get("results")?.as_array()?;
        let projected = rows
            .iter()
            .filter_map(Value::as_object)
            .map(Self::project_row)
            .collect::<Option<Vec<_>>>()?;
        result.insert("results".to_owned(), json!(projected));
        Some(Value::Object(result))
    }

    fn project_row(row: &serde_json::Map<String, Value>) -> Option<Value> {
        let text = |key| match row.get(key) {
            None | Some(Value::Null) => Some(""),
            Some(value) => value.as_str(),
        };
        let line = match row.get("line") {
            None | Some(Value::Null) => 0,
            Some(value) => value.as_i64()?,
        };
        let score = match row.get("score") {
            None | Some(Value::Null) => 0.0,
            Some(value) => value.as_f64()?,
        };
        let matched = match row.get("matched") {
            None => Vec::new(),
            Some(value) => value.as_array()?.iter().filter_map(Value::as_str).collect(),
        };
        Some(json!({
            "path": text("path")?, "line": line, "heading": text("heading")?,
            "score": if score == 0.0 { 0.0 } else { score },
            "matched": matched, "sources": text("sources")?,
        }))
    }

    fn search_args(root: &Path, fields: &serde_json::Map<String, Value>) -> Option<Vec<OsString>> {
        let limit = fields.get("limit")?.as_u64()?;
        let queries = fields
            .get("queries")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        if !root.join(".wikimap/index.db").is_file()
            || limit == 0
            || queries.is_empty()
            || queries
                .iter()
                .any(|value| value.is_empty() || value.starts_with('-') || value.contains('\0'))
        {
            return None;
        }
        let mut args = vec![
            "search".into(),
            "--json".into(),
            "-n".into(),
            limit.to_string().into(),
        ];
        args.extend(queries.into_iter().map(OsString::from));
        Some(args)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wikimap_projection_keeps_order_and_normalizes_vendor_fields() {
        let raw = json!({"results":[
            {"path":"한글.md","line":8,"score":1.25,"matched":["hit",42],"partial":"1/2"},
            false, {"path":"second.md","score":-0.0,"sources":"2/2"}],
            "weak":true, "partial":false, "notes":[{"body":"omitted"}]});
        assert_eq!(
            WikimapSearch::project_results(&raw.to_string()),
            Some(json!({
                "results":[
                    {"path":"한글.md","line":8,"heading":"","score":1.25,"matched":["hit"],"sources":""},
                    {"path":"second.md","line":0,"heading":"","score":0.0,"matched":[],"sources":"2/2"}],
                "weak":true, "partial":false, "fused":false
            }))
        );
    }

    #[test]
    fn wikimap_projection_defers_irregular_payloads_to_python() {
        for raw in [
            "broken",
            "[]",
            r#"{"results":{}}"#,
            r#"{"results":[],"weak":"nonempty"}"#,
            r#"{"results":[{"path":"x","line":"2"}]}"#,
            r#"{"results":[{"path":"x","score":NaN}]}"#,
            r#"{"results":[{"path":"x","matched":null}]}"#,
        ] {
            assert!(WikimapSearch::project_results(raw).is_none(), "{raw}");
        }
    }
}
