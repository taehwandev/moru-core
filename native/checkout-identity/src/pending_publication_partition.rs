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

    fn can_defer(
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

    pub(crate) fn might_defer<'a>(
        preflight: &Value,
        mut checkpoints: impl Iterator<Item = &'a str>,
    ) -> Option<bool> {
        let route = preflight.get("route")?.as_object()?;
        let envelope = route
            .get("request_classification")?
            .get("intent_envelope")?;
        if envelope.get("authority")?.as_str()? != "envelope"
            || !envelope.get("schema_valid")?.as_bool()?
            || !envelope.get("failures")?.as_array()?.is_empty()
        {
            return Some(false);
        }
        let (git_write, external_write) = match envelope.get("effective_effect")?.as_str()? {
            "read" | "local_write" => (false, false),
            "git_write" => (true, false),
            "external_write" | "destructive" => (true, true),
            _ => return None,
        };
        let commit_route = route.get("command")?.as_str()? == "commit";
        // Treat any specified local contract as potentially eligible. Actual
        // contract version, route floor and packet binding stay with admission.
        let local_delivery = route
            .get("local_delivery_contract")
            .is_some_and(|value| !value.is_null());
        Some(checkpoints.any(|name| {
            Self::can_defer(
                name,
                commit_route,
                local_delivery,
                git_write,
                external_write,
            )
        }))
    }
}
