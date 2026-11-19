//! Owner: bound publication receipt encoding and local persistence.
//! Allowed: regular-file reads, atomic sibling replacement, JSON and SHA-256.
//! Forbidden: Git/provider execution and publication decisions. Caller: completion probe.

use crate::{atomic_sibling::AtomicSibling, callback_state::LocalState, python_text::PythonText};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::CString,
    fs::{File, OpenOptions},
    io::{ErrorKind, Read},
    os::unix::fs::OpenOptionsExt,
    path::{Component, Path},
};

const MAX_RECEIPT: u64 = 256 * 1024;
const MAX_EVIDENCE: u64 = 4 * 1024 * 1024;

pub(crate) struct PendingPublicationReceipt;

impl PendingPublicationReceipt {
    pub(crate) fn replace(payload: &Value) -> Option<Value> {
        let evidence = Path::new(payload.get("evidence")?.as_str()?);
        let parent = evidence.parent()?;
        let run = parent.file_name()?.to_str()?;
        let temporary = payload.get("temporary")?.as_str()?;
        if !evidence.is_absolute()
            || evidence.file_name()?.to_str()? != "preflight.json"
            || !Self::is_id(run)
            || !Self::is_id(temporary)
            || !parent.parent()?.ends_with(".moru/runs")
            || evidence
                .components()
                .any(|part| part == Component::ParentDir)
        {
            return None;
        }
        let dir = AtomicSibling::open_directory(parent)?;
        let record = payload.get("record")?;
        if !Self::shape(record, run)
            || !Self::artifact_safe(record)
            || !Self::safe_artifact_text(evidence.to_str()?)
        {
            return None;
        }
        let evidence_file = AtomicSibling::open_relative(&dir, c"preflight.json", libc::O_RDONLY)?;
        let bound_bytes = Self::read_file(evidence_file, MAX_EVIDENCE)?.ok()?;
        let digest = format!("{:x}", Sha256::digest(bound_bytes));
        if record.get("evidence_sha256")?.as_str()? != digest {
            return None;
        }
        let encoded = Self::encode(record.clone())?;
        let temporary = CString::new(format!("pending-publication.json.{temporary}.tmp")).ok()?;
        let target = c"pending-publication.json";
        let result = AtomicSibling::Private.replace(&dir, &temporary, target, encoded.as_bytes());
        let error = result.err().map(|error| match error.kind() {
            ErrorKind::AlreadyExists => "FileExistsError",
            ErrorKind::NotFound => "FileNotFoundError",
            ErrorKind::PermissionDenied => "PermissionError",
            ErrorKind::IsADirectory => "IsADirectoryError",
            ErrorKind::NotADirectory => "NotADirectoryError",
            _ => "OSError",
        });
        Some(json!({"error": error}))
    }

    fn artifact_safe(value: &Value) -> bool {
        match value {
            Value::String(text) => Self::safe_artifact_text(text),
            Value::Array(items) => items.iter().all(Self::artifact_safe),
            Value::Object(fields) => fields
                .iter()
                .all(|(key, value)| Self::safe_artifact_text(key) && Self::artifact_safe(value)),
            _ => true,
        }
    }

    fn safe_artifact_text(text: &str) -> bool {
        if text == "project_local_never_sync" {
            return false;
        }
        let normalized = text.replace('\\', "/");
        let parts: Vec<_> = normalized.split('/').collect();
        !parts.windows(4).enumerate().any(|(index, window)| {
            window[0..2] == [".moru", "runs"]
                && Self::is_id(window[2])
                && matches!(window[3].strip_prefix("continuation.json"),
                    Some(rest) if rest.starts_with(['?', '#'])
                        || matches!(rest, "" | "\n") && index + 4 == parts.len())
        })
    }

    pub(super) fn is_id(text: &str) -> bool {
        text.len() == 32
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    }

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

    pub(super) fn read(path: &Path, limit: u64) -> Option<Result<Vec<u8>, ErrorKind>> {
        LocalState::safe_path(Path::new("/"), path)?;
        let file = match OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
        {
            Ok(file) => file,
            Err(error) => return Some(Err(error.kind())),
        };
        Self::read_file(file, limit)
    }

    fn read_file(file: File, limit: u64) -> Option<Result<Vec<u8>, ErrorKind>> {
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
