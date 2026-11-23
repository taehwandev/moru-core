//! owner: ordered read-only diagnostics from prepared preflight results.
//! allowed imports: Python text conventions and JSON.
//! forbidden imports: filesystem, process execution, authority and state writes.
//! callers/tests: completion probe, agent-preflight and parity fixtures.
//! verification: precedence, Unicode normalization, exact failure order.
use crate::text::Text;
use serde_json::{json, Value};

pub(super) struct PreflightFailures;

impl PreflightFailures {
    pub(super) fn collect(payload: &Value) -> Option<Value> {
        let route_status = payload.get("route_status")?.as_i64()?;
        let mut failures = Vec::new();
        if route_status != 0 {
            let stdout = payload.get("route_stdout")?.as_str()?;
            let stderr = payload.get("route_stderr")?.as_str()?;
            let reason = [stdout, stderr]
                .iter()
                .flat_map(|text| {
                    text.split(Text::is_py_space)
                        .filter(|word| !word.is_empty())
                })
                .collect::<Vec<_>>()
                .join(" ");
            let mut message = String::from("workflow route failed");
            if !reason.is_empty() {
                message.push_str(": ");
                message.extend(reason.chars().take(400));
            }
            failures.push(message);
        } else if !payload.get("route_parse_error")?.as_str()?.is_empty() {
            failures.push("workflow route output was not valid JSON".to_owned());
        } else {
            let missing = payload.get("route_missing")?;
            if !missing.is_null() && !missing.as_array()?.is_empty() {
                failures.push("workflow route reported missing documents".to_owned());
            }
        }
        if payload.get("git_status")?.as_i64()? != 0
            && !payload.get("git_review_only")?.as_bool()?
        {
            failures.push("git status failed".to_owned());
        }
        if payload.get("audit_status")?.as_i64()? != 0 {
            failures.push("VibeGuard audit failed".to_owned());
        }
        for failure in payload.get("hook_failures")?.as_array()? {
            failures.push(failure.as_str()?.to_owned());
        }
        Some(json!({"failures": failures}))
    }
}
