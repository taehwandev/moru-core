//! owner: read-only preparation of a v2 local publication observation;
//! allowed imports: registry inspection, local Git proof, receipt transition and UTC formatting;
//! forbidden imports: persistence, network, provider calls and Git writes;
//! callers/tests: completion probe and native registry settlement fixtures;
//! verification: latest binding, exact staged tree, checkpoint order, and write-free refusals.

use crate::{
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
        if record.get("schema_version")?.as_u64()? != 2 || !Self::supports(checkpoint) {
            return None;
        }
        let completed = RegistryRead::inspect("completed-binding", payload.get("binding")?)?;
        if !completed.as_bool()? {
            return Some(Self::refuse(
                "local delivery observation requires a completed bound run",
            ));
        }
        if !record.get("items")?.as_array()?.iter().any(|item| {
            item.get("checkpoint").and_then(Value::as_str) == Some(checkpoint)
                && item.get("state").and_then(Value::as_str) == Some("pending")
        }) {
            return Some(Self::refuse("that checkpoint is not pending"));
        }
        let proof = record.get("local_delivery")?;
        let targets: Vec<_> = proof.get("targets")?.as_object()?.keys().collect();
        let observation = LocalDeliveryObservation::probe(&json!({
            "project": payload.get("project")?,
            "recorded_project": proof.get("project")?,
            "recorded_common": proof.get("common")?,
            "base": record.get("base_head")?,
            "source": record.get("source_branch")?,
            "cached": proof.get("reviewed_commit").filter(|value| !value.is_null()).cloned().unwrap_or(json!("")),
            "expected": proof.get("staged_sha256")?,
            "checkpoint": checkpoint,
            "commit_declared": proof.get("commit_declared")?,
            "targets": targets,
        }))?;
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

    fn refuse(reason: &str) -> Value {
        json!({"record": null, "reason": reason})
    }
}
