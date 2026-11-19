//! owner: ordered candidate discovery for document reuse history;
//! allowed imports: guarded registry reads, path metadata, JSON;
//! forbidden imports: session binding, prior proof credit, writes and providers;
//! callers/tests: private document probe and reuse history parity fixtures;
//! verification: tail window, completed records, root ranking and lexical ties.
use super::DocTranscript;
use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::{
    fs,
    io::ErrorKind,
    os::unix::fs::MetadataExt,
    path::{Component, Path},
};

impl DocTranscript {
    pub(crate) fn reuse_run_ids(payload: &Value) -> Option<Value> {
        let root = supported_path(payload.get("path")?)?;
        let current = payload.get("current")?.as_str()?;
        let limit = usize::try_from(payload.get("limit")?.as_u64()?).ok()?;
        if limit == 0 || limit > 100 || !PendingPublicationReceipt::is_id(current) {
            return None;
        }
        let registry =
            Self::read_reuse_evidence(&root.join(".moru/run-registry.json"), 4 * 1024 * 1024)?;
        let runs = registry.get("runs").and_then(Value::as_array);
        let ids: Vec<_> = runs
            .into_iter()
            .flatten()
            .rev()
            .take(limit)
            .filter_map(|run| {
                if run.get("state")?.as_str()? != "completed" {
                    return None;
                }
                let id = run.get("run_id")?.as_str()?;
                let canonical_name = run
                    .get("evidence_name")
                    .is_none_or(|name| name.as_str() == Some("preflight.json"));
                (canonical_name && id != current && PendingPublicationReceipt::is_id(id))
                    .then_some(id)
            })
            .collect();
        Some(json!(ids))
    }

    pub(crate) fn rank_reuse_roots(payload: &Value) -> Option<Value> {
        let candidates = payload.get("candidates")?.as_array()?;
        let excluded = payload.get("excluded")?.as_array()?;
        let limit = usize::try_from(payload.get("limit")?.as_u64()?).ok()?;
        if candidates.len() > 256 || excluded.len() > 256 || limit > 8 {
            return None;
        }
        let excluded = excluded
            .iter()
            .map(supported_path)
            .collect::<Option<Vec<_>>>()?;
        let mut ranked = Vec::new();
        for candidate in candidates {
            let root = supported_path(candidate)?;
            if excluded.contains(&root) {
                continue;
            }
            let metadata = match fs::metadata(root.join(".moru/run-registry.json")) {
                Ok(metadata) if metadata.is_file() => metadata,
                Ok(_) => continue,
                Err(error) if absent(&error) => continue,
                Err(_) => return None,
            };
            // CPython ranks using st_mtime seconds as a double, so close
            // nanosecond values may tie and must use the path tiebreaker.
            let modified = metadata.mtime() as f64 + metadata.mtime_nsec() as f64 * 1e-9;
            ranked.push((modified, root));
        }
        ranked.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| b.1.cmp(&a.1)));
        let roots = ranked
            .iter()
            .take(limit)
            .map(|(_, root)| root.to_str())
            .collect::<Option<Vec<_>>>()?;
        Some(json!(roots))
    }
}

fn absent(error: &std::io::Error) -> bool {
    matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory)
}

fn supported_path(value: &Value) -> Option<&Path> {
    let text = value.as_str()?;
    let path = Path::new(text);
    (path.is_absolute()
        && !text.starts_with("//")
        && !path.components().any(|part| part == Component::ParentDir))
    .then_some(path)
}
