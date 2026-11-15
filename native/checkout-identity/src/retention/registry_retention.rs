//! Existing RegistryRead owner: bounded, lock-free retention snapshot reads.
//! Allowed: LocalState/PythonJson/stdlib; forbidden: writes, pruning, claiming
//! or acquiring/creating locks. Callers/tests: retention-state private probe,
//! original-source and report/apply authority regressions.
//! Verification: offline registry tests and parent original-Python report parity.
use super::RegistryRead;
use crate::{
    callback_state::LocalState,
    python_json::{PythonJson, Value as Py},
};
use serde_json::{json, Value};
use std::{collections::HashSet, path::Path};

impl RegistryRead {
    pub(super) fn retention_states(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 3
            || payload.get("int_digits")?.as_u64()?
                != option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
                    .unwrap_or("0")
                    .parse::<u64>()
                    .ok()?
        {
            return None;
        }
        let states = payload
            .get("states")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let directory = Path::new(payload.get("state_dir")?.as_str()?);
        if !directory.is_absolute() || directory.canonicalize().ok()?.as_path() != directory {
            return None;
        }
        LocalState::safe_path(Path::new("/"), directory)?;
        // Retention's report reads the atomically replaced registry without locks.
        // Ordinary registry readers have a different existing-lock contract.
        let text = LocalState::read(&directory.join("run-registry.json"), 1024 * 1024)?;
        Self::retention_rows(&text, &states)
    }

    fn retention_rows(text: &str, states: &[&str]) -> Option<Value> {
        // A parse decline preserves JSONDecodeError versus uncaught digit-limit
        // ValueError and unsupported-surrogate behavior in the original reader.
        let data = PythonJson::parse(text)?;
        let schema = match data.get("schema_version") {
            Some(Py::Bool(true)) => true,
            Some(Py::Number(number)) => number.equals_u64(1),
            _ => false,
        };
        let Some(rows) = data.get("runs").and_then(Py::as_array).filter(|_| schema) else {
            return Some(Value::Null);
        };
        let mut seen = HashSet::new();
        let mut result = Vec::with_capacity(rows.len());
        for row in rows {
            let Some(id) = row
                .get("run_id")
                .and_then(Py::as_str)
                .filter(|id| !id.is_empty())
            else {
                return Some(Value::Null);
            };
            let Some(state) = row
                .get("state")
                .and_then(Py::as_str)
                .filter(|state| states.contains(state))
            else {
                return Some(Value::Null);
            };
            if !seen.insert(id) {
                return Some(Value::Null);
            }
            result.push(json!([id, state]));
        }
        Some(Value::Array(result))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn python_schema_equality_and_insertion_order_are_preserved() {
        for version in ["true", "1", "1.0", "1e0"] {
            let text = format!(
                r#"{{"schema_version":{version},"runs":[{{"run_id":"z","state":"running"}},{{"run_id":"a","state":"paused"}}]}}"#
            );
            assert_eq!(
                RegistryRead::retention_rows(&text, &["running", "paused"]),
                Some(json!([["z", "running"], ["a", "paused"]]))
            );
        }
    }
    #[test]
    fn invalid_structures_return_unreadable_without_dropping_rows() {
        for text in [
            "[]",
            r#"{"schema_version":2,"runs":[]}"#,
            r#"{"schema_version":1,"runs":[{}]}"#,
            r#"{"schema_version":1,"runs":[{"run_id":"x","state":"other"}]}"#,
            r#"{"schema_version":1,"runs":[{"run_id":"x","state":"running"},{"run_id":"x","state":"running"}]}"#,
        ] {
            assert_eq!(
                RegistryRead::retention_rows(text, &["running"]),
                Some(Value::Null),
                "{text}"
            );
        }
    }
    #[test]
    fn ignored_nonfinite_and_large_numbers_do_not_change_valid_maps() {
        let text = format!(
            r#"{{"schema_version":1,"runs":[{{"run_id":"한글","state":"running","unused":NaN}}],"extra":{}}}"#,
            "9".repeat(1000)
        );
        assert_eq!(
            RegistryRead::retention_rows(&text, &["running"]),
            Some(json!([["한글", "running"]]))
        );
    }
    #[test]
    fn parse_or_surrogate_uncertainty_defers_to_original_errors() {
        for text in ["{", r#"{"schema_version":1,"runs":[],"extra":"\ud800"}"#] {
            assert!(RegistryRead::retention_rows(text, &["running"]).is_none());
        }
    }
}
