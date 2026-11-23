//! owner: exact-byte atomic replacement of ordinary execution capsule files.
//! allowed imports: guarded sibling writes, existing JSON codec and std.
//! forbidden imports: lifecycle authority, ledger writes and providers.
//! callers/tests: completion probe and native capsule persistence fixtures.
//! verification: byte parity, private mode, collision and scope checks.
use crate::{
    atomic_sibling::AtomicSibling, pending_publication_receipt::PendingPublicationReceipt,
};
use serde_json::{json, Value};
use std::{
    ffi::CString,
    path::{Component, Path},
};

pub(super) struct CapsuleArtifact;

impl CapsuleArtifact {
    pub(super) fn replace(payload: &Value) -> Option<Value> {
        let text = payload.get("path")?.as_str()?;
        let target = Path::new(text);
        let parent = target.parent()?;
        let run = parent.file_name()?.to_str()?;
        let temporary = payload.get("temporary")?.as_str()?;
        let record = payload.get("record")?;
        if !target.is_absolute()
            || target.file_name()?.to_str()? != "execution-capsule.json"
            || !parent.parent()?.ends_with(".moru/runs")
            || !PendingPublicationReceipt::is_id(run)
            || !PendingPublicationReceipt::is_id(temporary)
            || target.components().any(|part| part == Component::ParentDir)
            || !PendingPublicationReceipt::artifact_safe(record)
            || !PendingPublicationReceipt::safe_artifact_text(text)
        {
            return None;
        }
        let dir = AtomicSibling::open_directory(parent)?;
        let evidence = AtomicSibling::open_relative(&dir, c"preflight.json", libc::O_RDONLY)?;
        if !evidence.metadata().ok()?.is_file() {
            return None;
        }
        let encoded = PendingPublicationReceipt::encode(record.clone())?;
        let temporary = CString::new(format!("execution-capsule.json.{temporary}.tmp")).ok()?;
        let result = AtomicSibling::Private.replace(
            &dir,
            &temporary,
            c"execution-capsule.json",
            encoded.as_bytes(),
        );
        let errno = result
            .err()
            .map(|error| error.raw_os_error().unwrap_or(libc::EIO));
        Some(json!({"errno": errno}))
    }
}
