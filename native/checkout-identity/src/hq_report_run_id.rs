//! Owner: HQ run ID selection and filename grammar.
//! Allowed imports: Python text handling and JSON.
//! Forbidden imports: filesystem, environment, clocks, and report publication.
//! Callers/tests: HQ assembly and run ID probe fixtures.
use crate::text::Text;
use serde_json::{json, Value};

pub(super) struct HqReportRunId;

impl HqReportRunId {
    pub(super) fn valid(id: &str) -> bool {
        (1..=128).contains(&id.len())
            && !id.contains("..")
            && id.bytes().enumerate().all(|(i, b)| {
                b.is_ascii_alphanumeric() || b == b'_' || (i > 0 && matches!(b, b'.' | b'-'))
            })
    }

    // An interior whitespace run can never appear in a valid ID or the
    // literal origin "hq", even after Python collapses it to one space.
    fn field<'a>(request: &'a Value, key: &str) -> Option<&'a str> {
        match request.get(key)? {
            Value::Null => Some(""),
            Value::String(text) => Some(Text::py_strip(text)),
            _ => None,
        }
    }

    pub(super) fn resolve(request: &Value) -> Option<Value> {
        let mut id = Self::field(request, "env_id")?;
        if id.is_empty() {
            id = Self::field(request, "preflight_id")?;
        }
        if id.is_empty() {
            let origin = Self::field(request, "origin")?;
            if !origin.is_ascii() {
                return None;
            }
            if origin.eq_ignore_ascii_case("hq") {
                id = Self::field(request, "agent_id")?;
            }
        }
        Some(json!({"run_id": if Self::valid(id) { id } else { "" }}))
    }
}
