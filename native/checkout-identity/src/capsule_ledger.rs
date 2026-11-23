//! owner: ordered capsule parent-ledger diagnostics.
//! allowed imports: serde JSON and Python whitespace predicates.
//! forbidden imports: filesystem, evidence issuance, state mutation and providers.
//! callers/tests: completion probe and capsule ledger parity tests.
//! verification: exact observed-fact mismatches and intake entry precedence.
use super::capsule_json_integers;
use crate::python_text::PythonText;
use serde_json::{json, Value};

pub(super) struct CapsuleLedger;

impl CapsuleLedger {
    pub(super) fn check(payload: &Value) -> Option<Value> {
        let ledger = payload.get("ledger")?.as_object()?;
        let recorded_path = payload.get("recorded_path")?.as_str()?;
        let observed_path = payload.get("observed_path")?.as_str()?;
        let observed_hash = payload.get("observed_hash")?.as_str()?;
        let observed_route = payload.get("observed_route")?.as_str()?;
        let schema = ledger.get("schema_version");
        if schema.is_some_and(|value| !capsule_json_integers(value)) {
            return None;
        }
        let mut failures = Vec::new();
        if schema != Some(&Value::Bool(true)) && schema.and_then(Value::as_u64) != Some(1) {
            failures.push("execution capsule parent gate ledger schema does not match");
        }
        if recorded_path != observed_path {
            failures.push("execution capsule parent gate ledger preflight path does not match");
        }
        if ledger
            .get("preflight_evidence_sha256")
            .and_then(Value::as_str)
            != Some(observed_hash)
        {
            failures.push("execution capsule parent gate ledger preflight hash does not match");
        }
        if ledger.get("route_fingerprint").and_then(Value::as_str) != Some(observed_route) {
            failures.push("execution capsule parent gate ledger route does not match");
        }
        match ledger.get("entries").and_then(Value::as_array) {
            Some(entries) if entries.iter().all(Value::is_object) => {
                if !entries.iter().any(Self::intake_success) {
                    failures.push("execution capsule parent gate ledger lacks request intake SUCCESS evidence");
                }
            }
            _ => failures.push("execution capsule parent gate ledger entries are malformed"),
        }
        Some(json!({"failures": failures}))
    }

    fn intake_success(entry: &Value) -> bool {
        entry.get("gate").and_then(Value::as_str) == Some("request intake")
            && entry.get("status").and_then(Value::as_str) == Some("SUCCESS")
            && entry
                .get("evidence")
                .and_then(Value::as_str)
                .is_some_and(|evidence| evidence.chars().any(|c| !PythonText::whitespace(c)))
    }
}
