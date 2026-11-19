//! owner: AGY post-initial required-document transaction;
//! allowed imports: existing document, transcript, lock and atomic marker owners, JSON and std;
//! forbidden imports: session admission, providers and Git;
//! callers/tests: private probe and AGY delivery parity fixtures;
//! verification: exact output/marker, ordered decisions and terminal write failure.
use super::{
    delivery_marker::{DocDeliveryMarker, MARKER},
    delivery_text::DocDeliveryText,
    DocTranscript,
};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs,
    io::ErrorKind,
    path::{Path, PathBuf},
};

pub(super) fn deliver(payload: &Value) -> Option<Value> {
    let evidence = Path::new(payload.get("evidence")?.as_str()?);
    if evidence.file_name()?.to_str()? != "preflight.json" {
        return None;
    }
    let transcript = Path::new(payload.get("transcript")?.as_str()?);
    // Leave large and special-file profiles with the existing read-only
    // probes before this write-capable request starts a transcript scan.
    match fs::metadata(transcript) {
        Ok(meta) if meta.is_dir() || (meta.is_file() && meta.len() <= 4 * 1024 * 1024) => {}
        Err(error) if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) => {}
        _ => return None,
    }
    let marker = evidence.with_file_name(MARKER);
    if !marker.symlink_metadata().ok()?.is_file() {
        return None;
    }
    let destination = DocDeliveryMarker::open(&marker)?;
    // Python keeps the bounded wait for contended and unsupported cases.
    // Probe once so fallback does not spend two independent wait budgets.
    let lock = destination.try_lock()?;
    let plan = DocTranscript::delivery_plan(&marker, transcript, payload.get("limit")?.as_i64()?)?;
    let (response, pending, count) = match plan.get("action")?.as_str()? {
        "skip" => return Some(json!({"text": ""})),
        "upgrade" => (String::new(), plan.get("delivered")?.clone(), 0),
        "deliver" if plan.get("had_previous")?.as_bool()? => {
            let (text, pending) = prepare(evidence, transcript, payload)?;
            let count = plan
                .get("redeliveries")?
                .as_i64()?
                .checked_add(i64::from(!pending.is_empty()))?;
            (text, json!(pending), count)
        }
        _ => return None,
    };
    // Complete every eligibility check before entering the only mutation.
    if response.len() > 128 * 1024 {
        return None;
    }
    if !destination.is_current(evidence.parent()?, &lock)? {
        return None;
    }
    let success = json!({"text": response});
    let stored = destination.write(&json!({
        "temporary": payload.get("temporary")?.as_str()?,
        "delivered": pending,
        "offset": plan.get("offset")?.as_u64()?,
        "redeliveries": count,
    }))?;
    Some(if stored["stored"] == true {
        success
    } else {
        json!({"write_failed": true})
    })
}

fn prepare(evidence: &Path, transcript: &Path, payload: &Value) -> Option<(String, Vec<String>)> {
    let manifest = DocTranscript::read_delivery_manifest(evidence)?;
    let rules = Path::new(manifest.get(0)?.as_str()?);
    if !rules.is_absolute() || rules.to_str()?.starts_with("//") {
        return None;
    }
    let docs = manifest
        .get(1)?
        .as_array()?
        .iter()
        .map(Value::as_str)
        .collect::<Option<Vec<_>>>()?;
    let texts = if docs.is_empty() {
        json!({})
    } else {
        DocTranscript::read_documents(rules, &docs)?
    };
    let readable: Vec<_> = docs
        .iter()
        .copied()
        .filter(|doc| texts.get(doc).is_some())
        .collect();
    let covered = if readable.is_empty() {
        HashSet::new()
    } else {
        DocTranscript::agy_covered(transcript, rules, &readable)?
            .into_iter()
            .collect()
    };
    let pending: Vec<_> = docs
        .into_iter()
        .filter(|doc| !covered.contains(doc))
        .collect();
    let mut render_docs = Vec::new();
    for name in &pending {
        if let Some(text) = texts.get(name) {
            let path: PathBuf = rules.join(name).components().collect();
            render_docs.push(json!({"name": name, "text": text, "path": path.to_str()?}));
        }
    }
    let text = DocDeliveryText::render(&json!({
        "docs": render_docs,
        "inline_limit": payload.get("inline_limit")?,
        "total_limit": payload.get("total_limit")?,
    }))?;
    Some((text, pending.into_iter().map(str::to_owned).collect()))
}
