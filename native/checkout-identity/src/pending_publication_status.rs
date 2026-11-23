//! Owner: pending-checkpoint list and status text. Allowed: bound receipt
//! reader and JSON. Forbidden: action admission, Git/provider calls and writes.
//! Callers/tests: guarded completion probe and Python publication status.

use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use std::collections::HashSet;

pub(crate) struct PendingPublicationStatus;

impl PendingPublicationStatus {
    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let receipt = PendingPublicationReceipt::probe(payload)?;
        let declared = payload.get("declared")?.as_array()?;
        let mut seen = HashSet::new();
        let declared: Vec<&str> = declared
            .iter()
            .filter_map(Value::as_str)
            .filter(|name| PendingPublicationReceipt::checkpoint(name) && seen.insert(*name))
            .collect();
        let owed = Self::outstanding(&receipt, &declared)?;
        let reason = Self::reason(&owed);
        Some(json!({"owed": owed, "reason": reason}))
    }

    pub(super) fn outstanding(receipt: &Value, declared: &[&str]) -> Option<Vec<String>> {
        let record = receipt.get("record")?;
        let mut owed = Vec::new();
        if record.is_null() {
            let problem = receipt.get("problem")?.as_str()?;
            owed.extend(declared.iter().map(|name| (*name).to_owned()));
            if owed.is_empty() && problem != "missing" {
                owed.push(format!("receipt ({problem})"));
            }
            return Some(owed);
        }
        let mut recorded = HashSet::new();
        for item in record.get("items")?.as_array()? {
            let name = item.get("checkpoint")?.as_str()?;
            recorded.insert(name);
            if item.get("state")?.as_str()? == "pending" {
                owed.push(name.to_owned());
            }
        }
        owed.extend(
            declared
                .iter()
                .filter(|name| !recorded.contains(**name))
                .map(|name| (*name).to_owned()),
        );
        Some(owed)
    }

    pub(super) fn reason(owed: &[String]) -> String {
        if owed.is_empty() {
            return String::new();
        }
        format!(
            concat!(
                "Moru publication. finish passed, but declared publication is not yet observed ({}). ",
                "Perform it only under the run's admitted effect and the publication gate, then run ",
                "moru-hook pending-publication settle --run RUN_ID --checkpoint CHECKPOINT in the original checkout. Supply --observation-file PATH for a PR. ",
                "Never report it as published before then; if it cannot proceed, say it is NOT PUBLISHED and why."
            ),
            owed.join(", "),
        )
    }
}
