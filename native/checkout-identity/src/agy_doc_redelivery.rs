//! owner: AGY required-document delivery and redelivery transactions;
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

pub(super) struct AgyDocDelivery;

impl AgyDocDelivery {
    pub(super) fn redeliver(payload: &Value) -> Option<Value> {
        let evidence = Path::new(payload.get("evidence")?.as_str()?);
        if evidence.file_name()?.to_str()? != "preflight.json" {
            return None;
        }
        let transcript = Path::new(payload.get("transcript")?.as_str()?);
        bounded_transcript(transcript)?;
        let marker = evidence.with_file_name(MARKER);
        if !marker.symlink_metadata().ok()?.is_file() {
            return None;
        }
        let destination = DocDeliveryMarker::open(&marker)?;
        // Python keeps the bounded wait for contended and unsupported cases.
        // Probe once so fallback does not spend two independent wait budgets.
        let lock = destination.try_lock()?;
        let plan =
            DocTranscript::delivery_plan(&marker, transcript, payload.get("limit")?.as_i64()?)?;
        let (response, pending, count) = match plan.get("action")?.as_str()? {
            "skip" => return Some(json!({"text": ""})),
            "upgrade" => (String::new(), plan.get("delivered")?.clone(), 0),
            "deliver" if plan.get("had_previous")?.as_bool()? => {
                let manifest = DocTranscript::read_delivery_manifest(evidence)?;
                prepare(
                    manifest.get(0)?,
                    manifest.get(1)?,
                    transcript,
                    payload,
                    &plan,
                )?
            }
            _ => return None,
        };
        if !destination.is_current(evidence.parent()?, &lock)? {
            return None;
        }
        Self::finish(&destination, payload, &plan, response, pending, count)
    }

    pub(super) fn deliver_prepared(payload: &Value) -> Option<Value> {
        let evidence = Path::new(payload.get("evidence")?.as_str()?);
        if evidence.file_name()?.to_str()? != "preflight.json" {
            return None;
        }
        let plan = payload.get("plan")?;
        if plan.get("action")?.as_str()? != "deliver" {
            return None;
        }
        let transcript = Path::new(payload.get("transcript")?.as_str()?);
        bounded_transcript(transcript)?;
        let destination = DocDeliveryMarker::open(&evidence.with_file_name(MARKER))?;
        let (response, pending, count) = prepare(
            payload.get("rules")?,
            payload.get("docs")?,
            transcript,
            payload,
            plan,
        )?;
        Self::finish(&destination, payload, plan, response, pending, count)
    }

    fn finish(
        destination: &DocDeliveryMarker,
        payload: &Value,
        plan: &Value,
        response: String,
        pending: Value,
        count: i64,
    ) -> Option<Value> {
        // Complete every eligibility check before entering the only mutation.
        if response.len() > 128 * 1024 {
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
}

fn bounded_transcript(transcript: &Path) -> Option<()> {
    match fs::metadata(transcript) {
        Ok(meta) if meta.is_dir() || (meta.is_file() && meta.len() <= 4 * 1024 * 1024) => Some(()),
        Err(error) if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) => {
            Some(())
        }
        _ => None,
    }
}

fn prepare(
    rules: &Value,
    docs: &Value,
    transcript: &Path,
    payload: &Value,
    plan: &Value,
) -> Option<(String, Value, i64)> {
    let rules = Path::new(rules.as_str()?);
    if !rules.is_absolute() || rules.to_str()?.starts_with("//") {
        return None;
    }
    let docs = docs
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
    let count = plan.get("redeliveries")?.as_i64()?.checked_add(i64::from(
        plan.get("had_previous")?.as_bool()? && !pending.is_empty(),
    ))?;
    Some((text, json!(pending), count))
}
