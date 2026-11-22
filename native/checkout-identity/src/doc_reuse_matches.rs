//! owner: completed-run document snapshot matching;
//! allowed imports: guarded evidence reads, run ID validation, std and JSON;
//! forbidden imports: registry selection, takeaway credit, writes and providers;
//! callers/tests: private transcript probe and native required/project reuse parity;
//! verification: exact project/session/run binding, duplicate paths and lazy reads.
use super::DocTranscript;
use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::{collections::HashMap, fs, path::Path};

impl DocTranscript {
    pub(crate) fn reuse_matches(payload: &Value) -> Option<Value> {
        let root = Path::new(payload.get("path")?.as_str()?);
        let ids = payload.get("ids")?.as_array()?;
        let [runtime, session_id] = payload.get("session")?.as_array()?.as_slice() else {
            return None;
        };
        let project_docs = payload.get("project_docs")?.as_bool()?;
        let wanted = payload
            .get("wanted")?
            .as_array()?
            .iter()
            .map(|value| {
                let [path, hash, size] = value.as_array()?.as_slice() else {
                    return None;
                };
                Some((path.as_str()?, hash.as_str()?, size.as_u64()?))
            })
            .collect::<Option<Vec<_>>>()?;
        if ids.len() > 100
            || runtime.as_str()?.is_empty()
            || session_id.as_str()?.is_empty()
            || !root.is_absolute()
            || fs::canonicalize(root).ok()?.as_os_str() != root.as_os_str()
        {
            return None;
        }
        let runs = root.join(".moru/runs");
        for (index, id) in ids.iter().enumerate() {
            let id = id.as_str()?;
            if !PendingPublicationReceipt::is_id(id) {
                return None;
            }
            let prior =
                Self::read_reuse_evidence(&runs.join(id).join("preflight.json"), 8 * 1024 * 1024)?;
            if prior.get("agent_run_id").and_then(Value::as_str) != Some(id)
                || prior.pointer("/runtime_session/runtime") != Some(runtime)
                || prior.pointer("/runtime_session/session_id") != Some(session_id)
            {
                continue;
            }
            if prior.get("project")?.as_str()? != root.to_str()? {
                // Legacy preflights can spell the same root via a symlink or
                // relative path. Let pathlib decide those cases.
                return None;
            }
            let records = if project_docs {
                prior.get("project_route_docs")
            } else {
                match prior.get("execution_snapshot") {
                    Some(Value::Object(snapshot)) => snapshot.get("required_docs"),
                    None | Some(Value::Null) => None,
                    _ => return None,
                }
            };
            let records = match records {
                None | Some(Value::Null) => continue,
                Some(value) => value.as_array()?,
            };
            let mut by_path = HashMap::new();
            for record in records {
                let path = record.get("path")?.as_str()?;
                let hash = record.get("sha256")?.as_str()?;
                let size = record.get("size_bytes")?.as_u64()?;
                if hash.len() != 64
                    || !hash
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                {
                    return None;
                }
                by_path.insert(path, (hash, size));
            }
            let matches: Vec<_> = wanted
                .iter()
                .enumerate()
                .filter_map(|(position, &(path, hash, size))| {
                    (by_path.get(path) == Some(&(hash, size))).then_some(position)
                })
                .collect();
            if !matches.is_empty() {
                return Some(json!([index + 1, matches]));
            }
        }
        Some(json!([]))
    }
}
