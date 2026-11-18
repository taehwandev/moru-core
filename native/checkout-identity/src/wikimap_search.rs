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
        let update = match args {
            [_] => false,
            [_, operation] if operation == "update-v1" => true,
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
            .and_then(|packet| Self::execute(&source, &packet, update))
        else {
            return 125;
        };
        if serde_json::to_writer(io::stdout().lock(), &result).is_ok() {
            0
        } else {
            1
        }
    }

    fn execute(source: &Path, packet: &Value, update: bool) -> Option<Value> {
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
        let Some((stdout, stderr, status)) = capture_status(&mut command, Duration::from_secs(15))
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
                json!({"code": code, "stdout": stdout, "stderr": stderr})
            }
            None => json!({"failed": true}),
        })
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
