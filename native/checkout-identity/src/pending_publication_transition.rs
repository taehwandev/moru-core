//! Owner: pure pending-publication record transitions. Allowed: JSON and local
//! checkpoint validation. Forbidden: authorizing publication, checking Git or
//! providers, file I/O and clocks. Caller: guarded completion probe.

use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::collections::HashSet;

pub(crate) struct PendingPublicationTransition;

impl PendingPublicationTransition {
    pub(crate) fn prepare(payload: &Value) -> Option<Value> {
        if !PendingPublicationReceipt::lossless(payload) {
            return None;
        }
        let run = payload.get("run_id")?.as_str()?;
        let evidence = payload.get("evidence_sha256")?.as_str()?;
        let head = payload.get("base_head")?.as_str()?;
        let branch = payload.get("source_branch")?.as_str()?;
        let local = payload.get("local_delivery")?;
        if !local.is_null() && !local.is_object() {
            return None;
        }
        let mut items = Vec::new();
        let mut seen = HashSet::new();
        for checkpoint in payload.get("checkpoints")?.as_array()? {
            let checkpoint = checkpoint.as_str()?;
            if !PendingPublicationReceipt::checkpoint(checkpoint) {
                return None;
            }
            if seen.insert(checkpoint) {
                items
                    .push(json!({"checkpoint": checkpoint, "state": "pending", "observation": ""}));
            }
        }
        let mut record = json!({
            "schema_version": if local.is_null() { 1 } else { 2 },
            "run_id": run, "evidence_sha256": evidence, "base_head": head,
            "source_branch": branch, "items": items,
        });
        if !local.is_null() {
            record
                .as_object_mut()?
                .insert("local_delivery".into(), local.clone());
        }
        Some(json!({"record": record}))
    }

    pub(crate) fn observe(payload: &Value) -> Option<Value> {
        let checkpoint = payload.get("checkpoint")?.as_str()?;
        let observation = payload.get("observation")?.as_str()?;
        let observed_at = payload.get("observed_at")?.as_str()?;
        let mut record = payload.get("record")?.clone();
        if !PendingPublicationReceipt::lossless(&record)
            || !PendingPublicationReceipt::checkpoint(checkpoint)
        {
            return None;
        }
        let version = record.get("schema_version")?.as_u64()?;
        if !matches!(version, 1 | 2) {
            return None;
        }
        let item = record
            .get_mut("items")?
            .as_array_mut()?
            .iter_mut()
            .find(|item| {
                item.get("checkpoint").and_then(Value::as_str) == Some(checkpoint)
                    && item.get("state").and_then(Value::as_str) == Some("pending")
            })?
            .as_object_mut()?;
        item.insert("state".into(), json!("observed"));
        item.insert("observation".into(), json!(observation));
        item.insert("observed_at".into(), json!(observed_at));

        let tail = observation.rsplit(' ').next()?;
        let local =
            checkpoint == "publication.commit" || checkpoint.starts_with("publication.integrate/");
        if version == 2
            && local
            && (40..=64).contains(&tail.len())
            && tail
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            record
                .get_mut("local_delivery")?
                .as_object_mut()?
                .insert("reviewed_commit".into(), json!(tail));
        }
        Some(json!({"record": record}))
    }
}
