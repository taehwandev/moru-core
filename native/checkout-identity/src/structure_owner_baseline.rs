//! owner: bounded Git blob reads for declaration baselines.
//! allowed imports: read-only process capture, Python text boundaries and JSON.
//! forbidden imports: worktree writes, arbitrary revision expressions and review decisions.
//! callers/tests: structural review and real Git baseline parity fixtures.
//! verification: framing, revision selection, rename paths and per-blob fallback.
use crate::{python_text::PythonText, read_process::status::capture_status};
use serde_json::{json, Value};
use std::{
    path::{Component, Path},
    process::Command,
    time::Duration,
};

pub(super) struct StructureOwnerBaseline;

impl StructureOwnerBaseline {
    pub(super) fn batch(payload: &Value) -> Option<Value> {
        let root = Path::new(payload.get("project")?.as_str()?);
        let revision = payload.get("revision")?.as_str()?;
        let paths = payload.get("paths")?.as_array()?;
        if !root.is_absolute()
            || root.canonicalize().ok()? != root
            || (revision != "HEAD" && !Self::object_id(revision))
            || paths.len() > 256
        {
            return None;
        }
        let queries = paths
            .iter()
            .map(|value| {
                let path = value.as_str()?;
                let relative = Path::new(path);
                (!path.is_empty()
                    && !path.starts_with("./")
                    && !path.contains(['\n', '\r', '\0'])
                    && relative
                        .components()
                        .all(|part| matches!(part, Component::Normal(_))))
                .then(|| format!("{revision}:{path}"))
            })
            .collect::<Vec<_>>();
        let mut input = Vec::new();
        for query in queries.iter().flatten() {
            input.extend_from_slice(query.as_bytes());
            input.push(b'\n');
        }
        if input.is_empty() {
            return Some(json!({"rows": vec![Value::Null; paths.len()]}));
        }
        let (bytes, stderr, status) = capture_status(
            Command::new("git")
                .args(["cat-file", "--batch"])
                .current_dir(root)
                .env("GIT_OPTIONAL_LOCKS", "0")
                .env("GIT_TERMINAL_PROMPT", "0")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_ALLOW_PROTOCOL", ""),
            Duration::from_secs(2),
            Some(128 * 1024),
            Some(input),
        )
        .ok()??;
        if !status.success() || !stderr.is_empty() {
            return None;
        }
        Self::decode(&queries, &bytes)
    }

    fn object_id(text: &str) -> bool {
        matches!(text.len(), 40 | 64) && text.bytes().all(|byte| byte.is_ascii_hexdigit())
    }

    fn decode(queries: &[Option<String>], mut bytes: &[u8]) -> Option<Value> {
        let mut rows = Vec::with_capacity(queries.len());
        for query in queries {
            let Some(query) = query else {
                rows.push(Value::Null);
                continue;
            };
            let line_end = bytes.iter().position(|&byte| byte == b'\n')?;
            let header = std::str::from_utf8(&bytes[..line_end]).ok()?;
            bytes = &bytes[line_end + 1..];
            if header.strip_suffix(" missing") == Some(query.as_str()) {
                rows.push(json!([]));
                continue;
            }
            let (oid, info) = header.split_once(' ')?;
            let (kind, length) = info.split_once(' ')?;
            let length: usize = length.parse().ok()?;
            if !Self::object_id(oid) || bytes.get(length) != Some(&b'\n') {
                return None;
            }
            let body = &bytes[..length];
            bytes = &bytes[length + 1..];
            // The Python runner handles invalid UTF-8 and strips ANSI output.
            let lines = if kind == "blob" && !body.contains(&0x1b) {
                std::str::from_utf8(body).ok().map(PythonText::splitlines)
            } else {
                None
            };
            rows.push(json!(lines));
        }
        bytes.is_empty().then(|| json!({"rows": rows}))
    }
}
