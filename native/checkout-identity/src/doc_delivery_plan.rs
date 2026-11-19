//! owner: required-doc marker read and redelivery decision;
//! allowed imports: guarded local reader, transcript scans, JSON and std;
//! forbidden imports: marker writes, locks, providers, evidence authorization;
//! callers/tests: private doc-transcript probe and delivery parity fixtures;
//! verification: initial delivery, old marker upgrade, and compaction limits.
use super::DocTranscript;
use crate::python_json::{Number, ParseOutcome, PythonJson, Value as MarkerValue};
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::Path,
};

const MAX_MARKER: u64 = 256 * 1024;

impl DocTranscript {
    pub(crate) fn delivery_plan(marker: &Path, transcript: &Path, limit: i64) -> Option<Value> {
        if marker.file_name()?.to_str()? != "required-docs-delivered.json" {
            return None;
        }
        let (present, marker) = Self::read_delivery_marker(marker)?;
        let offset = match marker.get("transcript_bytes") {
            Some(MarkerValue::Number(Number::Integer(raw))) => Some(raw.parse::<i64>().ok()?),
            _ => None,
        };
        if present && offset.is_none() && !Self::compacted(transcript)? {
            let delivered = match marker.get("delivered").and_then(MarkerValue::as_array) {
                Some(items) => items
                    .iter()
                    .map(MarkerValue::as_str)
                    .collect::<Option<Vec<_>>>()?,
                None => Vec::new(),
            };
            return Some(
                json!({"action": "upgrade", "offset": Self::aligned(transcript, 0)?, "delivered": delivered}),
            );
        }
        let redeliveries = match marker.get("redeliveries") {
            None => 0,
            Some(MarkerValue::Number(Number::Integer(raw))) => raw.parse::<i64>().ok()?,
            _ => return None,
        };
        if let Some(offset) = offset {
            if !Self::due(transcript, offset, redeliveries, limit)? {
                return Some(json!({"action": "skip"}));
            }
        }
        Some(json!({
            "action": "deliver", "offset": Self::aligned(transcript, offset.unwrap_or(0))?,
            "had_previous": marker.as_object().is_some_and(|row| !row.is_empty()),
            "redeliveries": redeliveries,
        }))
    }

    fn read_delivery_marker(path: &Path) -> Option<(bool, MarkerValue)> {
        let metadata = match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.is_file() && metadata.len() <= MAX_MARKER => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => {
                return Some((false, MarkerValue::Null))
            }
            _ => return None,
        };
        let file = Self::open(path, &metadata)?.ok()?;
        let mut bytes = Vec::new();
        file.take(MAX_MARKER + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > MAX_MARKER {
            return None;
        }
        let text = std::str::from_utf8(&bytes).ok()?;
        let marker = match PythonJson::parse_outcome(text) {
            ParseOutcome::Value(marker) => marker,
            ParseOutcome::Invalid => MarkerValue::Null,
            ParseOutcome::Unsupported => return None,
        };
        Some((true, marker))
    }
}
