//! owner: NextLedger; allowed imports: local read-only files, PythonJson, binding/field helpers;
//! forbidden imports: ledger writes, gate acceptance authority, subprocess; callers: NextProcess;
//! verification: current-route chronological replay and supported freshness parity.
#[path = "next_ledger_binding.rs"]
mod binding;
#[path = "next_gate_fields.rs"]
mod fields;
#[path = "next_input_freshness.rs"]
mod freshness;
use crate::python_json::{PythonJson as Py, Value};
use std::{collections::BTreeSet, fs, path::Path};
include!(concat!(env!("OUT_DIR"), "/next_contract.rs"));
pub(super) struct NextLedger;
impl NextLedger {
    pub fn read(
        evidence: &Path,
        path: &Path,
        preflight: &Value,
        bytes: &[u8],
    ) -> Option<BTreeSet<String>> {
        let mut recorded = BTreeSet::new();
        let text = match fs::read_to_string(path) {
            Ok(text) => text,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Some(recorded),
            Err(_) => return None,
        };
        let parsed = Py::parse(&text)?;
        if !Py::truthy(&parsed) {
            return Some(recorded);
        }
        let ledger = parsed.as_object()?;
        if ledger.get("invalid_json").is_some_and(Py::truthy) {
            return Some(recorded);
        }
        let contract: serde_json::Value = serde_json::from_str(CONTRACT).ok()?;
        let contract = &contract["ledger"];
        let empty = crate::python_json::Object::new();
        let route = match preflight.get("route").filter(|v| Py::truthy(v)) {
            Some(v) => v.as_object()?,
            None => &empty,
        };
        if !binding::LedgerBinding::matches(
            ledger,
            evidence,
            route,
            bytes,
            contract["schema"].as_u64()?,
        )? {
            return Some(recorded);
        }
        let required = match route.get("gates").filter(|v| Py::truthy(v)) {
            Some(v) => v
                .as_array()?
                .iter()
                .map(Py::string)
                .collect::<BTreeSet<_>>(),
            None => BTreeSet::new(),
        };
        let entries = match ledger.get("entries") {
            Some(v) => v.as_array()?,
            None => return Some(recorded),
        };
        for entry in entries {
            let Some(entry) = entry.as_object() else {
                continue;
            };
            let gate = entry
                .get("gate")
                .filter(|v| Py::truthy(v))
                .map(Py::string)
                .unwrap_or_default();
            if !required.contains(&gate) {
                continue;
            }
            recorded.remove(&gate);
            let status = entry
                .get("status")
                .filter(|v| Py::truthy(v))
                .map(Py::string)
                .unwrap_or_default();
            if status != "SUCCESS" {
                continue;
            }
            if let Some(snapshot) = entry.get("reuse_snapshot").filter(|v| Py::truthy(v)) {
                let Some(snapshot) = snapshot.as_object() else {
                    continue;
                };
                if binding::LedgerBinding::equals(snapshot.get("schema_version"), 2) {
                    if !freshness::InputFreshness::valid(snapshot, evidence)? {
                        continue;
                    }
                } else if !binding::LedgerBinding::equals(snapshot.get("schema_version"), 1) {
                    continue;
                }
            }
            if fields::GateFields::recorded(&gate, entry, contract)? {
                recorded.insert(gate);
            }
        }
        Some(recorded)
    }
}
#[cfg(test)]
#[path = "next_ledger_tests.rs"]
mod tests;
