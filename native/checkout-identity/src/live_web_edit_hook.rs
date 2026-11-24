//! owner: interpret PostToolUse edit events and submit the prepared record.
//! allowed imports: Python JSON, read-only path resolution and the edit log.
//! forbidden imports: hook installation, lifecycle policy and network.
//! callers/tests: path_claims.record_from_hook and live-web edit fixtures.
//! verification: event selection, project containment and native append receipt.
use super::live_web_edit_log::LiveWebEditLog;
use crate::{
    discovery_fs::DiscoveryFs,
    python_json::{InputDiagnostic, PythonJson},
};
use serde_json::{json, Value};
use std::{env, io, path::Path};

pub(super) struct LiveWebEditHook;

impl LiveWebEditHook {
    pub(super) fn record(input: &Value) -> Option<io::Result<Value>> {
        let raw = input.get("payload")?.as_str()?;
        let holder = input.get("holder")?.as_str()?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let handled = || Some(Ok(json!({"handled": true})));
        let payload = match PythonJson::parse_with_diagnostic(raw, Some(limit), None) {
            Ok(Some(payload)) => payload,
            Err(InputDiagnostic::Syntax(_)) => return handled(),
            _ => return None,
        };
        if !matches!(
            payload.get("tool_name").and_then(|value| value.as_str()),
            Some("Edit" | "Write" | "MultiEdit" | "NotebookEdit")
        ) {
            return handled();
        }
        let Some(tool_input) = payload.get("tool_input") else {
            return handled();
        };
        let path = tool_input
            .get("file_path")
            .filter(|value| PythonJson::truthy(value))
            .or_else(|| tool_input.get("notebook_path"));
        let Some(path) = path
            .and_then(|value| value.as_str())
            .filter(|path| !path.is_empty())
        else {
            return handled();
        };

        let project = match input.get("project")? {
            Value::Null => match payload.get("cwd").filter(|value| PythonJson::truthy(value)) {
                Some(value) => {
                    let Some(cwd) = value.as_str() else {
                        return handled();
                    };
                    DiscoveryFs::resolve(Path::new(cwd))?
                }
                None => DiscoveryFs::resolve(&env::current_dir().ok()?)?,
            },
            value => DiscoveryFs::resolve(Path::new(value.as_str()?))?,
        };
        let Some(relative) = LiveWebEditLog::relative_path(&project, path)? else {
            return handled();
        };
        LiveWebEditLog::append(&json!({
            "project": project.to_str()?,
            "entry": {"session": holder, "files": [relative]},
        }))
        .map(|result| result.map(|_| json!({"handled": true})))
    }
}
