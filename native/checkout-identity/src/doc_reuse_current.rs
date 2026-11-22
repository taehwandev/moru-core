//! owner: current-run document reuse input;
//! allowed imports: guarded evidence reads, snapshot row validation, std and JSON;
//! forbidden imports: registry scans, takeaway credit, evidence writes and providers;
//! callers/tests: private reuse-current probe and native required/project reuse parity;
//! verification: canonical path and session binding, ordering, malformed legacy input.
use super::{doc_reuse_snapshot::ReuseSnapshot, DocTranscript};
use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::{collections::HashSet, fs, path::Path};

impl DocTranscript {
    pub(crate) fn reuse_current(payload: &Value) -> Option<Value> {
        let path = Path::new(payload.get("path")?.as_str()?);
        let project_docs = payload.get("project_docs")?.as_bool()?;
        let run = path.parent()?;
        let run_id = run.file_name()?.to_str()?;
        let project = run.parent()?.parent()?.parent()?;
        if !path.is_absolute()
            || path.file_name()?.to_str()? != "preflight.json"
            || !PendingPublicationReceipt::is_id(run_id)
            || run.parent()? != project.join(".moru/runs")
        {
            return None;
        }
        let current = Self::read_reuse_evidence(path, 8 * 1024 * 1024)?;
        let runtime = current.pointer("/runtime_session/runtime")?.as_str()?;
        let session = current.pointer("/runtime_session/session_id")?.as_str()?;
        let project = project.to_str()?;
        if current.get("project")?.as_str()? != project
            || runtime.is_empty()
            || session.is_empty()
            || fs::canonicalize(path).ok()?.as_os_str() != path.as_os_str()
        {
            return None;
        }
        let docs = if project_docs {
            Vec::new()
        } else {
            required_names(&current)?
        };
        let rows = if project_docs || !docs.is_empty() {
            ReuseSnapshot::from_preflight(&current, project_docs)?
                .records()
                .collect::<Option<Vec<_>>>()?
        } else {
            Vec::new()
        };
        Some(json!([docs, rows, [project, run_id, runtime, session]]))
    }
}

fn required_names(current: &Value) -> Option<Vec<&str>> {
    let entries = match current.get("route") {
        Some(Value::Object(route)) => route.get("required_docs"),
        None | Some(Value::Null) => None,
        _ => return None,
    };
    let mut names = Vec::new();
    let mut seen = HashSet::new();
    if let Some(value) = entries.filter(|value| !value.is_null()) {
        for doc in value.as_array()? {
            let doc = doc.as_str()?;
            if seen.insert(doc) {
                names.push(doc);
            }
        }
    }
    Some(names)
}
