//! Owner: classify deferred publication checkpoints after route admission.
//! Allowed: JSON and canonical checkpoint spelling. Forbidden: granting
//! permissions, reading run state, executing Git or writing receipts.

use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};

pub(crate) struct PendingPublicationPartition;

impl PendingPublicationPartition {
    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let commit_route = payload.get("commit_route")?.as_bool()?;
        let local_delivery = payload.get("local_delivery")?.as_bool()?;
        let git_write = payload.get("git_write")?.as_bool()?;
        let external_write = payload.get("external_write")?.as_bool()?;
        let checkpoints = payload.get("checkpoints")?.as_array()?;
        let deferred: Vec<bool> = checkpoints
            .iter()
            .map(|entry| {
                let Some(name) = entry
                    .as_str()
                    .filter(|name| PendingPublicationReceipt::checkpoint(name))
                else {
                    return false;
                };
                Self::can_defer(
                    name,
                    commit_route,
                    local_delivery,
                    git_write,
                    external_write,
                )
            })
            .collect();
        Some(json!({"deferred": deferred}))
    }

    pub(crate) fn can_defer(
        name: &str,
        commit_route: bool,
        local_delivery: bool,
        git_write: bool,
        external_write: bool,
    ) -> bool {
        match name.split('/').next().unwrap_or("") {
            "publication.commit" => git_write && (commit_route || local_delivery),
            "publication.integrate" => git_write && local_delivery,
            "publication.push" | "publication.pull-request" => external_write && commit_route,
            _ => false,
        }
    }
}
