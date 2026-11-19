//! Owner: bounded local publication-receipt reading and evidence binding.
//! Allowed: regular-file reads, JSON and SHA-256. Forbidden: changes to state,
//! Git/provider execution and publication decisions. Caller: completion probe.

use crate::{callback_state::LocalState, python_text::PythonText};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::OpenOptions,
    io::{ErrorKind, Read},
    os::unix::fs::OpenOptionsExt,
    path::{Component, Path},
};

const MAX_RECEIPT: u64 = 256 * 1024;
const MAX_EVIDENCE: u64 = 4 * 1024 * 1024;

pub(crate) struct PendingPublicationReceipt;

impl PendingPublicationReceipt {
    pub(crate) fn encode(mut record: Value) -> Option<String> {
        if !record.is_object() || !Self::lossless(&record) {
            return None;
        }
        record.sort_all_objects();
        let json = serde_json::to_string_pretty(&record).ok()?;
        let mut encoded = PythonText::escape_json_unicode(&json);
        encoded.push('\n');
        (encoded.len() as u64 <= MAX_RECEIPT).then_some(encoded)
    }

    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let evidence = Path::new(payload.get("evidence")?.as_str()?);
        let run_id = evidence.parent()?.file_name()?.to_str()?;
        if !evidence.is_absolute()
            || evidence.starts_with("/dev")
            || evidence.starts_with("/proc")
            || evidence
                .components()
                .any(|part| part == Component::ParentDir)
        {
            return None;
        }
        let receipt = evidence.with_file_name("pending-publication.json");
        let bytes = match Self::read(&receipt, MAX_RECEIPT)? {
            Ok(bytes) => bytes,
            Err(ErrorKind::NotFound) => return Some(Self::problem("missing")),
            Err(_) => return Some(Self::problem("unreadable")),
        };
        if std::str::from_utf8(&bytes).is_err() {
            return Some(Self::problem("unreadable"));
        }
        // Python additionally accepts lone surrogates, wider numbers and nonfinite
        // values. Let the reference own parse errors and any lossy numeric profile.
        let record: Value = serde_json::from_slice(&bytes).ok()?;
        if !Self::lossless(&record) {
            return None;
        }
        if !Self::shape(&record, run_id) {
            return Some(Self::problem("foreign or malformed"));
        }
        let evidence_payload = match Self::read(evidence, MAX_EVIDENCE)? {
            Ok(bytes) => bytes,
            Err(_) => return Some(Self::problem("foreign or malformed")),
        };
        let expected = format!("{:x}", Sha256::digest(evidence_payload));
        if record.get("evidence_sha256")?.as_str()? != expected {
            return Some(Self::problem("foreign or malformed"));
        }
        Some(json!({"record": record, "problem": ""}))
    }

    fn read(path: &Path, limit: u64) -> Option<Result<Vec<u8>, ErrorKind>> {
        LocalState::safe_path(Path::new("/"), path)?;
        let file = match OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
        {
            Ok(file) => file,
            Err(error) => return Some(Err(error.kind())),
        };
        let metadata = file.metadata().ok()?;
        if metadata.is_dir() {
            return Some(Err(ErrorKind::IsADirectory));
        }
        if !metadata.is_file() || metadata.len() > limit {
            return None;
        }
        let mut bytes = Vec::new();
        match file.take(limit + 1).read_to_end(&mut bytes) {
            Ok(_) => (bytes.len() as u64 <= limit).then_some(Ok(bytes)),
            Err(error) => Some(Err(error.kind())),
        }
    }

    fn shape(record: &Value, run_id: &str) -> bool {
        matches!(
            record.get("schema_version").and_then(Value::as_u64),
            Some(1 | 2)
        ) && record.get("run_id").and_then(Value::as_str) == Some(run_id)
            && record
                .get("evidence_sha256")
                .and_then(Value::as_str)
                .is_some()
            && record
                .get("base_head")
                .and_then(Value::as_str)
                .is_some_and(|head| !head.is_empty())
            && record
                .get("items")
                .and_then(Value::as_array)
                .is_some_and(|items| {
                    items.iter().all(|item| {
                        item.get("checkpoint")
                            .and_then(Value::as_str)
                            .is_some_and(Self::checkpoint)
                            && matches!(
                                item.get("state").and_then(Value::as_str),
                                Some("pending" | "observed")
                            )
                    })
                })
    }

    pub(super) fn checkpoint(name: &str) -> bool {
        if matches!(name, "publication.commit" | "publication.push") {
            return true;
        }
        let Some((kind, target)) = name.split_once('/') else {
            return false;
        };
        matches!(kind, "publication.pull-request" | "publication.integrate")
            && (1..=200).contains(&target.len())
            && target.as_bytes()[0].is_ascii_alphanumeric()
            && target
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._/-".contains(&byte))
    }

    pub(super) fn lossless(value: &Value) -> bool {
        match value {
            Value::Number(value) => !value.is_f64(),
            Value::Array(items) => items.iter().all(Self::lossless),
            Value::Object(fields) => fields.values().all(Self::lossless),
            _ => true,
        }
    }

    fn problem(problem: &str) -> Value {
        json!({"record": null, "problem": problem})
    }
}
