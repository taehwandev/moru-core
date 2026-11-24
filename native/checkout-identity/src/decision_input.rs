//! owner: validate the parsed research decision input in caller order.
//! allowed imports: Python whitespace, JSON types and in-memory identity sets.
//! forbidden imports: credential reads, network, cache and filesystem effects.
//! callers/tests: DecisionCachePlan; test_microsoft_decision.
//! verification: exact first-error and Python rollback on unsupported transport.
use crate::python_text::PythonText;
use serde_json::Value;
use std::collections::HashSet;

pub(crate) struct DecisionInput;

impl DecisionInput {
    pub(crate) fn validate(payload: &Value) -> Result<(), &'static str> {
        let query = payload
            .get("query")
            .and_then(Value::as_str)
            .ok_or("Input needs a query and sources")?;
        let sources = payload
            .get("sources")
            .and_then(Value::as_array)
            .filter(|_| !blank(query))
            .ok_or("Input needs a nonempty query and a sources array")?;
        let mut seen = HashSet::new();
        for source in sources {
            let source = source.as_object().ok_or("Each source must be an object")?;
            for field in ["id", "url", "title", "text"] {
                if source.get(field).and_then(Value::as_str).is_none_or(blank) {
                    return Err("Each source needs id, url, title, and text");
                }
            }
            let id = source["id"]
                .as_str()
                .ok_or("Each source needs id, url, title, and text")?;
            if !seen.insert(id) {
                return Err("Source ids must be unique");
            }
            if source
                .get("required")
                .is_some_and(|value| !value.is_boolean())
            {
                return Err("required must be a boolean");
            }
            if source
                .get("published_at")
                .is_some_and(|value| !value.is_string())
            {
                return Err("published_at must be a string");
            }
        }
        Ok(())
    }
}

fn blank(text: &str) -> bool {
    text.trim_matches(PythonText::whitespace).is_empty()
}
