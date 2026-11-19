//! owner: canonical required-document marker directory, lock and atomic write;
//! allowed imports: guarded sibling storage, file identity, JSON and Python text encoding;
//! forbidden imports: evidence selection, Git and providers;
//! callers/tests: private doc delivery probe and marker parity fixtures;
//! verification: exact bytes, collision refusal, modes and terminal writes.
use crate::{
    atomic_sibling::AtomicSibling, pending_publication_receipt::PendingPublicationReceipt,
    python_text::PythonText,
};
use serde_json::{json, Value};
use std::{ffi::CString, fs::File, os::unix::fs::MetadataExt, path::Path};

pub(super) const MARKER: &str = "required-docs-delivered.json";
const LOCK: &std::ffi::CStr = c"required-docs-delivered.json.lock";

pub(super) struct DocDeliveryMarker {
    dir: File,
}

impl DocDeliveryMarker {
    pub(super) fn write_payload(payload: &Value) -> Option<Value> {
        let marker = Path::new(payload.get("marker")?.as_str()?);
        Self::open(marker)?.write(payload)
    }

    pub(super) fn open(marker: &Path) -> Option<Self> {
        let parent = marker.parent()?;
        if marker.file_name()?.to_str()? != MARKER
            || !parent.parent()?.ends_with(".moru/runs")
            || !PendingPublicationReceipt::is_id(parent.file_name()?.to_str()?)
        {
            return None;
        }
        let dir = AtomicSibling::open_directory(parent)?;
        let evidence = AtomicSibling::open_relative(&dir, c"preflight.json", libc::O_RDONLY)?;
        if !evidence.metadata().ok()?.is_file() {
            return None;
        }
        Some(Self { dir })
    }

    pub(super) fn try_lock(&self) -> Option<File> {
        AtomicSibling::try_append_lock(&self.dir, LOCK)
    }

    pub(super) fn is_current(&self, parent: &Path, lock: &File) -> Option<bool> {
        let opened = self.dir.metadata().ok()?;
        let current = parent.metadata().ok()?;
        let held = lock.metadata().ok()?;
        let named = parent.join(LOCK.to_str().ok()?).symlink_metadata().ok()?;
        Some(
            (opened.dev(), opened.ino()) == (current.dev(), current.ino())
                && (held.dev(), held.ino()) == (named.dev(), named.ino()),
        )
    }

    pub(super) fn write(&self, payload: &Value) -> Option<Value> {
        let temporary = payload.get("temporary")?.as_str()?;
        if !PendingPublicationReceipt::is_id(temporary) {
            return None;
        }
        let delivered = payload
            .get("delivered")?
            .as_array()?
            .iter()
            .map(|item| serde_json::to_string(item.as_str()?).ok())
            .collect::<Option<Vec<_>>>()?;
        let offset = payload.get("offset")?.as_u64()?;
        let count = payload.get("redeliveries")?.as_i64()?;
        let text = PythonText::escape_json_unicode(&format!(
            "{{\"delivered\": [{}], \"transcript_bytes\": {offset}, \"redeliveries\": {count}}}",
            delivered.join(", ")
        ));
        if text.len() > 256 * 1024 {
            return None;
        }
        let temporary =
            CString::new(format!("required-docs-delivered.json.{temporary}.tmp")).ok()?;
        let result = AtomicSibling::InheritUmask.replace(
            &self.dir,
            &temporary,
            c"required-docs-delivered.json",
            text.as_bytes(),
        );
        Some(json!({"stored": result.is_ok()}))
    }
}
