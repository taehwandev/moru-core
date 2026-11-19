//! owner: canonical required-document marker write;
//! allowed imports: guarded atomic sibling storage, JSON and Python text encoding;
//! forbidden imports: evidence selection, lock acquisition, Git and providers;
//! callers/tests: private doc delivery probe and marker parity fixtures;
//! verification: exact bytes, collision refusal, modes and terminal writes.
use crate::{
    atomic_sibling::AtomicSibling, pending_publication_receipt::PendingPublicationReceipt,
    python_text::PythonText,
};
use serde_json::{json, Value};
use std::{ffi::CString, path::Path};

pub(super) fn write(payload: &Value) -> Option<Value> {
    let marker = Path::new(payload.get("marker")?.as_str()?);
    let temporary = payload.get("temporary")?.as_str()?;
    let parent = marker.parent()?;
    if marker.file_name()?.to_str()? != "required-docs-delivered.json"
        || !parent.parent()?.ends_with(".moru/runs")
        || !PendingPublicationReceipt::is_id(parent.file_name()?.to_str()?)
        || !PendingPublicationReceipt::is_id(temporary)
    {
        return None;
    }
    let dir = AtomicSibling::open_directory(parent)?;
    let evidence = AtomicSibling::open_relative(&dir, c"preflight.json", libc::O_RDONLY)?;
    if !evidence.metadata().ok()?.is_file() {
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
    let temporary = CString::new(format!("required-docs-delivered.json.{temporary}.tmp")).ok()?;
    let result = AtomicSibling::InheritUmask.replace(
        &dir,
        &temporary,
        c"required-docs-delivered.json",
        text.as_bytes(),
    );
    Some(json!({"stored": result.is_ok()}))
}
