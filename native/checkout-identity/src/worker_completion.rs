//! owner: pure worker-result completion; allowed imports: serde_json;
//! forbidden: files, processes, scheduling and providers; callers/tests:
//! worker_completion_process, worker_completion_contract; verification: parity.
use serde_json::Value;

pub(crate) struct WorkerCompletion;

impl WorkerCompletion {
    pub(crate) fn accepts(input: &Value) -> bool {
        if input.get("returncode").and_then(Value::as_i64) != Some(0) {
            return false;
        }
        let Some(packet) = input.get("packet").and_then(Value::as_object) else {
            return false;
        };
        if serde_json::to_vec(packet).map_or(true, |raw| raw.len() > 4096)
            || packet.get("schema_version").and_then(Value::as_str) != Some("worker_result_v1")
            || ["summary", "next_action"]
                .iter()
                .any(|k| !packet.get(*k).is_some_and(Value::is_string))
            || ["blockers", "changed_paths", "findings", "checks"]
                .iter()
                .any(|k| !packet.get(*k).is_some_and(Value::is_array))
            || !packet.get("artifacts").is_some_and(Value::is_object)
        {
            return false;
        }
        if !packet["blockers"].as_array().unwrap().is_empty()
            || packet["changed_paths"]
                .as_array()
                .unwrap()
                .iter()
                .any(|p| !p.is_string())
            || packet["artifacts"]
                .as_object()
                .unwrap()
                .values()
                .any(|p| !p.is_string())
            || packet["findings"]
                .as_array()
                .unwrap()
                .iter()
                .any(|f| !f.is_object())
        {
            return false;
        }
        let checks = packet["checks"].as_array().unwrap();
        if checks.is_empty()
            || checks.iter().any(|c| {
                c.get("exit_code").and_then(Value::as_i64).is_none()
                    || !c.get("outcome").is_some_and(Value::is_string)
            })
        {
            return false;
        }
        match packet.get("status").and_then(Value::as_str) {
            Some("findings") => input.get("allow_findings").and_then(Value::as_bool) == Some(true),
            Some("ok") => checks
                .iter()
                .all(|c| c["exit_code"].as_i64() == Some(0) && c["outcome"] == "pass"),
            _ => false,
        }
    }
}
