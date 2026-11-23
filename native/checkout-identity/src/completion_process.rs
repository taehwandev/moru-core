//! Owner: private bounded completion-policy JSON protocol.
//! Allowed: existing source guard, completion owners, receipt identity, std/JSON.
//! Forbidden: shells, providers, policy/state writes or public authority.
//! Callers/tests: thin completion adapter; native completion and bundle tests.
use crate::pending_publication_partition::PendingPublicationPartition;
use crate::pending_publication_status::PendingPublicationStatus;
use crate::publication_evidence::PublicationEvidence;
use crate::{
    completion_progress::Progress, completion_quality::Quality,
    completion_requirements::Requirements, legacy_publication_head::LegacyPublicationHead,
    local_delivery_identity::LocalDeliveryIdentity,
    local_delivery_observation::LocalDeliveryObservation,
    local_delivery_prepare::LocalDeliveryPrepare,
    pending_publication_receipt::PendingPublicationReceipt,
    pending_publication_transition::PendingPublicationTransition, pretool_guard::CallbackGuard,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
    os::fd::AsFd,
};

#[path = "capsule_binding.rs"]
mod capsule_binding;

pub(crate) struct CompletionProcess;

#[path = "pending_publication_settlement.rs"]
pub(super) mod pending_publication_settlement;

impl CompletionProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2 || CallbackGuard::root(launcher, "completion-probe").is_none() {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        let Ok(payload) = serde_json::from_slice::<Value>(&bytes) else {
            return 125;
        };
        // This operation only writes stdout. The caller owns any file behind it.
        if args[1] == "pending-publication-encode" {
            let Some(encoded) = PendingPublicationReceipt::encode(payload) else {
                return 125;
            };
            // Stdout's console wrapper can suppress EBADF. The underlying
            // file descriptor must report errors to the atomic-write caller.
            let Ok(descriptor) = std::io::stdout().as_fd().try_clone_to_owned() else {
                return 1;
            };
            let mut output = std::fs::File::from(descriptor);
            return i32::from(
                output
                    .write_all(encoded.as_bytes())
                    .and_then(|_| output.flush())
                    .is_err(),
            );
        }
        let result = match args[1].to_str() {
            Some("capsule-binding") => capsule_binding::CapsuleBinding::fingerprint(&payload),
            Some("quality") => Quality::inspect(&payload),
            Some("requirements") => Requirements::validate(&payload),
            Some("coverage") => Requirements::coverage(&payload),
            Some("progress") => Progress::inspect(&payload),
            Some("staged-v1") => LocalDeliveryIdentity::capture(&payload),
            Some("staged-v1-observe") => LocalDeliveryObservation::probe(&payload),
            Some("legacy-publication-head") => LegacyPublicationHead::probe(&payload),
            Some("publication-upstream-config") => LegacyPublicationHead::upstream(&payload),
            Some("publication-pr-proof") => PublicationEvidence::pull_request(&payload),
            Some("publication-upstream-proof") => PublicationEvidence::upstream(&payload),
            Some("staged-v1-prepare") => LocalDeliveryPrepare::probe(&payload),
            Some("pending-publication-read") => PendingPublicationReceipt::probe(&payload),
            Some("pending-publication-replace") => PendingPublicationReceipt::replace(&payload),
            Some("pending-publication-status") => PendingPublicationStatus::probe(&payload),
            Some("pending-publication-partition") => PendingPublicationPartition::probe(&payload),
            Some("pending-publication-prepare") => PendingPublicationTransition::prepare(&payload),
            Some("pending-publication-observe") => PendingPublicationTransition::observe(&payload),
            Some("pending-publication-local-settlement") => {
                pending_publication_settlement::LocalSettlement::prepare(&payload)
            }
            _ => None,
        };
        let Some(result) = result else {
            return 125;
        };
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1,"result":result}))
        else {
            return 1;
        };
        output.push(b'\n');
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }
}
