//! owner: WikimapSearch; allowed imports: source guard, ReadProcess, std, JSON and SHA-256.
//! forbidden imports: shell, index maintenance policy, routing or provider calls.
//! callers/tests: private launcher probe and workflow Wikimap adapter.
//! verification: pinned script, closed search arguments and subprocess parity.
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
        if args.len() != 1 {
            return 125;
        }
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
            .and_then(|packet| Self::execute(&source, &packet))
        else {
            return 125;
        };
        if serde_json::to_writer(io::stdout().lock(), &result).is_ok() {
            0
        } else {
            1
        }
    }

    fn execute(source: &Path, packet: &Value) -> Option<Value> {
        let fields = packet.as_object()?;
        if fields.len() != 3 {
            return None;
        }
        let root = Path::new(fields.get("root")?.as_str()?);
        let limit = fields.get("limit")?.as_u64()?;
        let queries = fields
            .get("queries")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        if !root.is_absolute()
            || !root.join(".wikimap/index.db").is_file()
            || limit == 0
            || queries.is_empty()
            || queries
                .iter()
                .any(|value| value.is_empty() || value.starts_with('-') || value.contains('\0'))
        {
            return None;
        }
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
            .args(["search", "--json", "-n"])
            .arg(limit.to_string())
            .args(queries)
            .current_dir(root);
        let Some((stdout, stderr, status)) = capture_status(&mut command, Duration::from_secs(15))
            .ok()
            .flatten()
        else {
            return Some(json!({"failed": true}));
        };
        let code = status
            .code()
            .or_else(|| status.signal().map(|signal| -signal))?;
        Some(json!({
            "code": code,
            "stdout": String::from_utf8(stdout).ok()?,
            "stderr": String::from_utf8(stderr).ok()?,
        }))
    }
}
