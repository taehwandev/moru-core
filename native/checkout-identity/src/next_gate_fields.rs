//! owner: GateFields; allowed imports: PythonJson, PythonText, serde_json contract, std;
//! forbidden imports: gate writes or finish authority; callers/tests: NextLedger;
//! verification: synthesis truthiness, latest-record and surface predicate fixtures.
use crate::{
    python_json::{Object, PythonJson as Py, Value as PyValue},
    python_text::PythonText,
};
use serde_json::Value;
use std::collections::BTreeMap;
pub(super) struct GateFields;
impl GateFields {
    pub fn recorded(gate: &str, entry: &Object, contract: &Value) -> Option<bool> {
        let evidence = entry
            .get("evidence")
            .filter(|v| Py::truthy(v))
            .map(Py::string)
            .unwrap_or_default();
        let mut fields = BTreeMap::new();
        if let Some(value) = entry.get("fields").filter(|v| Py::truthy(v)) {
            for (key, value) in value.as_object()?.iter() {
                if !matches!(value, PyValue::Null) {
                    fields.insert(key.clone(), Py::string(value));
                }
            }
        }
        let get = |name: &str| fields.get(name).map(String::as_str).unwrap_or("");
        let required = contract["required"]
            .get(gate)
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let missing = required
            .iter()
            .any(|name| Self::blank(get(name.as_str().unwrap())));
        let prose = Self::includes(&contract["prose"], gate) && !Self::blank(&evidence);
        if prose && missing {
            return Some(true);
        }
        if !prose && missing {
            return Some(false);
        }
        if gate == "multi-agent split decision" {
            let mode = get("mode")
                .trim_matches(PythonText::whitespace)
                .to_lowercase();
            let parallel = contract["parallel_fields"].as_array()?;
            if !Self::includes(&contract["serial"], &mode)
                && parallel
                    .iter()
                    .any(|k| Self::blank(get(k.as_str().unwrap())))
            {
                return Some(false);
            }
            if !Self::includes(&contract["serial"], &get("mode").to_lowercase())
                && parallel
                    .iter()
                    .any(|k| !fields.contains_key(k.as_str().unwrap()))
            {
                return None;
            }
        }
        if let Some(closed) = contract["closed_fields"].get(gate) {
            for (name, options) in closed.as_object()? {
                if !Self::includes(
                    options,
                    &get(name)
                        .trim_matches(PythonText::whitespace)
                        .to_lowercase(),
                ) {
                    return Some(false);
                }
            }
        }
        if gate == "work surface resolution" {
            return Self::surface(&fields, contract);
        }
        if Self::includes(&contract["renderers"], gate) {
            return Some(true);
        }
        let generic = fields.iter().any(|(key, value)| {
            Some(key.as_str()) != contract["capsule_field"].as_str() && !Self::blank(value)
        });
        Some(!evidence.is_empty() || generic)
    }
    fn surface(fields: &BTreeMap<String, String>, contract: &Value) -> Option<bool> {
        let mut text = String::new();
        for part in contract["surface_template"].as_array()? {
            text.push_str(part[0].as_str()?);
            if let Some(field) = part[1].as_str() {
                text.push_str(fields.get(field)?);
            }
        }
        let text = text.trim_matches(PythonText::whitespace);
        // Keep rare Unicode case expansion/version differences on the reference path.
        if text
            .chars()
            .any(|c| !c.is_ascii() && c.to_lowercase().to_string() != c.to_string())
        {
            return None;
        }
        let normalized = text.to_ascii_lowercase();
        let labels = contract["surface_labels"]
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let positions = labels
            .iter()
            .map(|label| normalized.find(label))
            .collect::<Option<Vec<_>>>()?;
        let mut values = BTreeMap::new();
        for (index, label) in labels.iter().enumerate() {
            let start = positions[index] + label.len();
            let end = positions[index + 1..]
                .iter()
                .filter(|p| **p >= start)
                .min()
                .copied()
                .unwrap_or(text.len());
            values.insert(*label, text[start..end].trim_matches([' ', ';']));
        }
        let empty =
            |value: &str| Self::includes(&contract["surface_empty"], &value.to_ascii_lowercase());
        Some(
            values["result="].eq_ignore_ascii_case("resolved")
                && matches!(values["search hops="], "1" | "2" | "3" | "4")
                && [
                    "owner=",
                    "anchors=",
                    "verified surface paths=",
                    "nearest falsifying verification=",
                ]
                .iter()
                .all(|k| !empty(values[k]))
                && !empty(values["evidence chain="])
                && values["evidence chain="].contains("->"),
        )
    }
    fn includes(values: &Value, needle: &str) -> bool {
        values
            .as_array()
            .is_some_and(|values| values.iter().any(|v| v.as_str() == Some(needle)))
    }
    fn blank(text: &str) -> bool {
        text.chars().all(PythonText::whitespace)
    }
}
