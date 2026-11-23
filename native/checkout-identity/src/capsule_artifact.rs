//! owner: bounded reads and exact-byte atomic replacement of execution capsules.
//! allowed imports: guarded sibling access, JSON codec, SHA-256 and std.
//! forbidden imports: lifecycle authority, ledger writes and providers.
//! callers/tests: completion probe and native capsule persistence fixtures.
//! verification: byte parity, private mode, collision and scope checks.
use super::capsule_shape::{CapsuleShape, CAPSULE_VERSION};
use crate::{
    atomic_sibling::AtomicSibling, pending_publication_receipt::PendingPublicationReceipt,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::{CStr, CString},
    fs::File,
    io::{ErrorKind, Read},
    path::{Component, Path},
};

pub(super) struct CapsuleArtifact;

const MAX_READ_BYTES: u64 = 256 * 1024;
const MAX_EVIDENCE_BYTES: u64 = 4 * 1024 * 1024;

impl CapsuleArtifact {
    pub(super) fn read(payload: &Value) -> Option<Value> {
        let target = Path::new(payload.get("path")?.as_str()?);
        let dir = AtomicSibling::open_directory(Self::run_parent(target)?)?;
        let file = match AtomicSibling::open_relative_result(
            &dir,
            c"execution-capsule.json",
            libc::O_RDONLY,
        ) {
            Ok(file) => file,
            Err(error) if error.kind() == ErrorKind::NotFound => {
                return Some(json!({"record": {}}));
            }
            Err(_) => return None,
        };
        let meta = file.metadata().ok()?;
        if meta.is_dir() {
            return Some(json!({"record": {"invalid_json": true}}));
        }
        if !meta.is_file() || meta.len() > MAX_READ_BYTES {
            return None;
        }
        let mut bytes = Vec::new();
        file.take(MAX_READ_BYTES + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > MAX_READ_BYTES
            || bytes
                .split(|byte| !byte.is_ascii_digit())
                .any(|digits| digits.len() > 640)
        {
            // Python can reject an oversized integer token even if a later
            // duplicate key overwrites it. Preserve its runtime digit policy.
            return None;
        }
        let record: Value = serde_json::from_slice(&bytes).ok()?;
        if !record.is_object() {
            return Some(json!({"record": {"invalid_json": true}}));
        }
        PendingPublicationReceipt::lossless(&record).then_some(json!({"record": record}))
    }

    pub(super) fn replace(payload: &Value) -> Option<Value> {
        let text = payload.get("path")?.as_str()?;
        let temporary = payload.get("temporary")?.as_str()?;
        let record = payload.get("record")?;
        Self::replace_record(text, temporary, record)
    }

    pub(super) fn refresh(payload: &Value) -> Option<Value> {
        let text = payload.get("path")?.as_str()?;
        let dir = AtomicSibling::open_directory(Self::run_parent(Path::new(text))?)?;
        Self::refresh_observed(&dir, payload, None)
    }

    pub(super) fn refresh_observed(
        dir: &File,
        payload: &Value,
        expected_hashes: Option<(&str, Option<&str>)>,
    ) -> Option<Value> {
        let text = payload.get("path")?.as_str()?;
        Self::run_parent(Path::new(text))?;
        let observed = payload.get("observed")?.as_object()?;
        let docs = observed.get("required_docs")?;
        let ledger_valid = payload.get("ledger_valid")?.as_bool()?;
        let phase = if !docs.is_null() && ledger_valid {
            "ready"
        } else {
            "preflight"
        };
        let preflight = Self::file_record(dir, c"preflight.json", false)??;
        let ledger = Self::file_record(dir, c"gate-evidence.json", true)?;
        if let Some((preflight_hash, ledger_hash)) = expected_hashes {
            if preflight["sha256"].as_str()? != preflight_hash
                || ledger.as_ref().and_then(|record| record["sha256"].as_str()) != ledger_hash
            {
                return None;
            }
        }
        let mut record = json!({
            "schema_version": CAPSULE_VERSION,
            "created_at": observed.get("created_at")?,
            "phase": phase,
            "route_fingerprint": observed.get("route_fingerprint")?,
            "request_fingerprint": observed.get("request_fingerprint")?,
            "preflight_evidence": preflight,
            "required_docs": if docs.is_null() { json!([]) } else { docs.clone() },
            "project_git": observed.get("project_git")?,
            "rules_git": observed.get("rules_git")?,
            "reuse_policy": CapsuleShape::reuse_policy(),
        });
        if let Some(ledger) = ledger {
            record["gate_ledger"] = ledger;
        }
        if CapsuleShape::capsule(&record)?.is_some() {
            return None;
        }
        let outcome = Self::write_record(dir, text, payload.get("temporary")?.as_str()?, &record)?;
        if outcome.get("errno")?.is_null() {
            Some(json!({"errno": null, "record": record}))
        } else {
            Some(outcome)
        }
    }

    pub(super) fn file_record(dir: &File, name: &CStr, optional: bool) -> Option<Option<Value>> {
        let file = match AtomicSibling::open_relative_result(dir, name, libc::O_RDONLY) {
            Ok(file) => file,
            Err(error) if optional && error.kind() == ErrorKind::NotFound => return Some(None),
            Err(_) => return None,
        };
        let meta = file.metadata().ok()?;
        if !meta.is_file() {
            return None;
        }
        if meta.len() > MAX_EVIDENCE_BYTES {
            return None;
        }
        let mut file = file.take(MAX_EVIDENCE_BYTES + 1);
        let mut hasher = Sha256::new();
        let mut buffer = [0; 32 * 1024];
        loop {
            let count = file.read(&mut buffer).ok()?;
            if count == 0 {
                break;
            }
            hasher.update(&buffer[..count]);
        }
        if file.limit() == 0 {
            return None;
        }
        Some(Some(json!({
            "filename": name.to_str().ok()?,
            "sha256": format!("{:x}", hasher.finalize()),
        })))
    }

    fn replace_record(text: &str, temporary: &str, record: &Value) -> Option<Value> {
        let target = Path::new(text);
        let parent = Self::run_parent(target)?;
        let dir = AtomicSibling::open_directory(parent)?;
        let evidence = AtomicSibling::open_relative(&dir, c"preflight.json", libc::O_RDONLY)?;
        if !evidence.metadata().ok()?.is_file() {
            return None;
        }
        Self::write_record(&dir, text, temporary, record)
    }

    fn write_record(dir: &File, text: &str, temporary: &str, record: &Value) -> Option<Value> {
        if !PendingPublicationReceipt::is_id(temporary)
            || !PendingPublicationReceipt::artifact_safe(record)
            || !PendingPublicationReceipt::safe_artifact_text(text)
        {
            return None;
        }
        let encoded = PendingPublicationReceipt::encode(record.clone())?;
        let temporary = CString::new(format!("execution-capsule.json.{temporary}.tmp")).ok()?;
        let result = AtomicSibling::Private.replace(
            dir,
            &temporary,
            c"execution-capsule.json",
            encoded.as_bytes(),
        );
        let errno = result
            .err()
            .map(|error| error.raw_os_error().unwrap_or(libc::EIO));
        Some(json!({"errno": errno}))
    }

    fn run_parent(target: &Path) -> Option<&Path> {
        let parent = target.parent()?;
        let run = parent.file_name()?.to_str()?;
        (target.is_absolute()
            && target.file_name()?.to_str()? == "execution-capsule.json"
            && parent.parent()?.ends_with(".moru/runs")
            && PendingPublicationReceipt::is_id(run)
            && !target.components().any(|part| part == Component::ParentDir))
        .then_some(parent)
    }
}
