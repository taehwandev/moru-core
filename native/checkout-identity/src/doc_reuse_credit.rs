//! owner: completed-run document takeaway credit;
//! allowed imports: guarded file reads, JSON and Python-compatible whitespace;
//! forbidden imports: session selection, approval, writes and providers;
//! callers/tests: private document probe and mandatory/project doc parity fixtures;
//! verification: latest entry, bounded proof text, duplicate handling and display cap.
use super::DocTranscript;
use crate::{pending_publication_receipt::PendingPublicationReceipt, python_text::PythonText};
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::Path,
};

impl DocTranscript {
    pub(crate) fn reuse_credit(payload: &Value) -> Option<Value> {
        let prior = Path::new(payload.get("path")?.as_str()?);
        let run = prior.parent()?;
        if prior.file_name()?.to_str()? != "preflight.json"
            || !prior.is_absolute()
            || !run.parent()?.ends_with(".moru/runs")
            || !PendingPublicationReceipt::is_id(run.file_name()?.to_str()?)
        {
            return None;
        }
        let slots = usize::try_from(payload.get("slots")?.as_u64()?).ok()?;
        let chars = usize::try_from(payload.get("chars")?.as_u64()?).ok()?;
        let existing = payload.get("takeaways")?.as_array()?;
        if slots > 3 || chars > 400 || existing.len() > 3 {
            return None;
        }
        let existing = existing
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let ledger = Self::read_reuse_evidence(&run.join("gate-evidence.json"), 8 * 1024 * 1024)?;
        let source = source_doc_takeaway(&ledger, chars)?;
        let review = Self::read_reuse_evidence(&run.join("doc-takeaway.json"), (chars * 8) as u64)?;
        let review = normalize(review.get("takeaway"), chars)?;
        let merged = match (source.is_empty(), review.is_empty()) {
            (true, true) => return Some(json!([false, null])),
            (true, false) => review,
            (false, true) => source,
            (false, false) if source == review => source,
            (false, false) => format!("{source} | {review}"),
        };
        Some(if existing.iter().any(|text| text.contains(&merged)) {
            json!([true, null])
        } else if existing.len() < slots {
            json!([true, merged])
        } else {
            json!([false, null])
        })
    }

    pub(super) fn read_reuse_evidence(path: &Path, limit: u64) -> Option<Value> {
        let metadata = match fs::metadata(path) {
            Ok(metadata) if metadata.is_file() && metadata.len() <= limit => metadata,
            Err(error)
                if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) =>
            {
                return Some(Value::Null);
            }
            _ => return None,
        };
        let file = Self::open(path, &metadata)?.ok()?;
        let mut bytes = Vec::new();
        file.take(limit + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > limit {
            return None;
        }
        serde_json::from_slice(&bytes).ok()
    }
}

fn source_doc_takeaway(ledger: &Value, chars: usize) -> Option<String> {
    let entry = ledger
        .get("entries")
        .and_then(Value::as_array)
        .and_then(|entries| {
            entries
                .iter()
                .rev()
                .find(|entry| entry.get("gate").and_then(Value::as_str) == Some("source docs"))
        });
    match entry {
        Some(entry) if entry.get("status").and_then(Value::as_str) == Some("SUCCESS") => {
            match entry.get("fields") {
                None | Some(Value::Null) => Some(String::new()),
                Some(Value::Object(fields)) => normalize(fields.get("takeaway"), chars),
                _ => None,
            }
        }
        _ => Some(String::new()),
    }
}

fn normalize(value: Option<&Value>, limit: usize) -> Option<String> {
    match value {
        None | Some(Value::Null) => Some(String::new()),
        Some(Value::String(text)) => Some(
            text.split(PythonText::whitespace)
                .filter(|word| !word.is_empty())
                .collect::<Vec<_>>()
                .join(" ")
                .chars()
                .take(limit)
                .collect(),
        ),
        _ => None,
    }
}
