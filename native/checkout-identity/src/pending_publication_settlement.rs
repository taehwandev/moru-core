//! owner: read-only preparation of a local publication observation;
//! allowed imports: registry inspection, local Git proof, receipt transition and UTC formatting;
//! forbidden imports: persistence, network, provider calls and Git writes;
//! callers/tests: completion probe and native registry settlement fixtures;
//! verification: latest binding, exact staged tree, checkpoint order, and write-free refusals.

use crate::{
    legacy_publication_head::LegacyPublicationHead,
    local_delivery_observation::LocalDeliveryObservation,
    pending_publication_receipt::PendingPublicationReceipt,
    pending_publication_transition::PendingPublicationTransition, registry_read::RegistryRead,
    status_snapshot::StatusSnapshot,
};
use serde_json::{json, Value};

pub(crate) struct LocalSettlement;

impl LocalSettlement {
    pub(crate) fn supports(checkpoint: &str) -> bool {
        PendingPublicationReceipt::checkpoint(checkpoint)
            && (checkpoint == "publication.commit"
                || checkpoint.starts_with("publication.integrate/"))
    }

    pub(crate) fn prepare(payload: &Value) -> Option<Value> {
        let record = payload.get("record")?;
        let checkpoint = payload.get("checkpoint")?.as_str()?;
        let version = record.get("schema_version")?.as_u64()?;
        if !matches!(version, 1 | 2) || !Self::supports(checkpoint) {
            return None;
        }
        if version == 2 {
            let completed = RegistryRead::inspect("completed-binding", payload.get("binding")?)?;
            if !completed.as_bool()? {
                return Some(Self::refuse(
                    "local delivery observation requires a completed bound run",
                ));
            }
        }
        if !record.get("items")?.as_array()?.iter().any(|item| {
            item.get("checkpoint").and_then(Value::as_str) == Some(checkpoint)
                && item.get("state").and_then(Value::as_str) == Some("pending")
        }) {
            return Some(Self::refuse("that checkpoint is not pending"));
        }
        let project = payload.get("project")?;
        let observation = if version == 1 {
            Self::legacy_observation(project, record, checkpoint)?
        } else {
            Self::bound_observation(project, record, checkpoint)?
        };
        let reason = observation.get("reason")?.as_str()?;
        if !reason.is_empty() {
            return Some(Self::refuse(reason));
        }
        let transition = PendingPublicationTransition::observe(&json!({
            "record": record, "checkpoint": checkpoint,
            "observation": observation.get("observation")?,
            "observed_at": StatusSnapshot::capture_time()?,
        }))?;
        Some(json!({"record": transition.get("record")?, "reason": ""}))
    }

    fn legacy_observation(project: &Value, record: &Value, checkpoint: &str) -> Option<Value> {
        if checkpoint != "publication.commit" {
            return Some(
                json!({"reason": "local integration requires a bound staged-content proof"}),
            );
        }
        let source = match record.get("source_branch") {
            None | Some(Value::Null) => "",
            Some(value) => value.as_str()?,
        };
        let base = record.get("base_head")?.as_str()?;
        let proof = LegacyPublicationHead::probe(&json!({
            "project": project, "source": source, "base": base, "requires_commit": true,
        }))?;
        let reason = proof.get("reason")?.as_str()?;
        if !reason.is_empty() {
            return Some(proof);
        }
        let head = proof.get("head")?.as_str()?;
        Some(json!({"reason": "", "observation": format!("HEAD {head} descends from {base}")}))
    }

    fn bound_observation(project: &Value, record: &Value, checkpoint: &str) -> Option<Value> {
        let proof = record.get("local_delivery")?;
        let targets: Vec<_> = proof.get("targets")?.as_object()?.keys().collect();
        LocalDeliveryObservation::probe(&json!({
            "project": project,
            "recorded_project": proof.get("project")?,
            "recorded_common": proof.get("common")?,
            "base": record.get("base_head")?,
            "source": record.get("source_branch")?,
            "cached": proof.get("reviewed_commit").filter(|value| !value.is_null()).cloned().unwrap_or(json!("")),
            "expected": proof.get("staged_sha256")?,
            "checkpoint": checkpoint,
            "commit_declared": proof.get("commit_declared")?,
            "targets": targets,
        }))
    }

    fn refuse(reason: &str) -> Value {
        json!({"record": null, "reason": reason})
    }
}
