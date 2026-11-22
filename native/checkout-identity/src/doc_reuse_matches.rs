//! owner: completed-run document snapshot matching;
//! allowed imports: guarded evidence reads, run ID validation, std and JSON;
//! forbidden imports: registry selection, takeaway credit, writes and providers;
//! callers/tests: private transcript probe and native required/project reuse parity;
//! verification: exact project/session/run binding, duplicate paths and lazy reads.
use super::DocTranscript;
use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};

impl DocTranscript {
    pub(crate) fn reuse_matches(payload: &Value) -> Option<Value> {
        let ids = payload.get("ids")?.as_array()?;
        if ids.len() > 100 {
            return None;
        }
        let search = ReuseSearch::prepare(payload)?;
        for (index, id) in ids.iter().enumerate() {
            let id = id.as_str()?;
            let run = search.run_dir(id)?;
            let matches = search.matching_indices(&run, id)?;
            if !matches.is_empty() {
                return Some(json!([index + 1, matches]));
            }
        }
        Some(json!([]))
    }
}

pub(super) struct ReuseSearch<'a> {
    pub(super) root: &'a Path,
    runs: PathBuf,
    runtime: &'a Value,
    session_id: &'a Value,
    project_docs: bool,
    wanted: Vec<(&'a str, &'a str, u64)>,
}

impl<'a> ReuseSearch<'a> {
    pub(super) fn prepare(payload: &'a Value) -> Option<Self> {
        let root = Path::new(payload.get("path")?.as_str()?);
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
        if runtime.as_str()?.is_empty()
            || session_id.as_str()?.is_empty()
            || !root.is_absolute()
            || fs::canonicalize(root).ok()?.as_os_str() != root.as_os_str()
        {
            return None;
        }
        Some(Self {
            root,
            runs: root.join(".moru/runs"),
            runtime,
            session_id,
            project_docs,
            wanted,
        })
    }

    pub(super) fn wanted_len(&self) -> usize {
        self.wanted.len()
    }

    pub(super) fn run_dir(&self, id: &str) -> Option<PathBuf> {
        PendingPublicationReceipt::is_id(id).then(|| self.runs.join(id))
    }

    pub(super) fn matching_indices(&self, run: &Path, id: &str) -> Option<Vec<usize>> {
        let prior =
            DocTranscript::read_reuse_evidence(&run.join("preflight.json"), 8 * 1024 * 1024)?;
        if prior.get("agent_run_id").and_then(Value::as_str) != Some(id)
            || prior.pointer("/runtime_session/runtime") != Some(self.runtime)
            || prior.pointer("/runtime_session/session_id") != Some(self.session_id)
        {
            return Some(Vec::new());
        }
        if prior.get("project")?.as_str()? != self.root.to_str()? {
            // Legacy preflights can spell the same root via a symlink or
            // relative path. Let pathlib decide those cases.
            return None;
        }
        let records = if self.project_docs {
            prior.get("project_route_docs")
        } else {
            match prior.get("execution_snapshot") {
                Some(Value::Object(snapshot)) => snapshot.get("required_docs"),
                None | Some(Value::Null) => None,
                _ => return None,
            }
        };
        let records = match records {
            None | Some(Value::Null) => return Some(Vec::new()),
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
        Some(
            self.wanted
                .iter()
                .enumerate()
                .filter_map(|(position, &(path, hash, size))| {
                    (by_path.get(path) == Some(&(hash, size))).then_some(position)
                })
                .collect(),
        )
    }
}
