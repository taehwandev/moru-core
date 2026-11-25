//! owner: read-only retention owner liveness; allowed: signal zero and process metadata;
//! forbidden: process mutation, writes and registry decisions;
//! callers/tests: maintenance retention; verification: live/dead and PID reuse parity.
use serde_json::Value;
use std::{fs, io};

pub(super) struct MaintenanceOwner;

impl MaintenanceOwner {
    pub(super) fn recorded_pid(owner: Option<&Value>) -> Option<Option<i32>> {
        match owner.and_then(|value| value.get("pid")) {
            None | Some(Value::Null) => Some(None),
            Some(value) => {
                let pid = i32::try_from(value.as_i64()?).ok()?;
                Some((pid > 0).then_some(pid))
            }
        }
    }

    pub(super) fn gone(owner: Option<&Value>) -> Option<bool> {
        let Some(pid) = Self::recorded_pid(owner)? else {
            return Some(true);
        };
        // Only ESRCH proves that the PID is absent. Never send a real signal.
        if unsafe { libc::kill(pid, 0) } < 0
            && io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH)
        {
            return Some(true);
        }
        let recorded = match owner.and_then(|value| value.get("start_token")) {
            None | Some(Value::Null) => return Some(false),
            Some(value) => value.as_str()?,
        };
        if recorded.is_empty() {
            return Some(false);
        }
        Some(Self::birth_token(pid).is_some_and(|current| recorded != current))
    }

    fn birth_token(pid: i32) -> Option<String> {
        if let Ok(raw) = fs::read(format!("/proc/{pid}/stat")) {
            let stat = String::from_utf8_lossy(&raw);
            if let Some(token) = stat.rsplit_once(')').and_then(|(_, tail)| {
                tail.split(crate::python_text::PythonText::whitespace)
                    .filter(|part| !part.is_empty())
                    .nth(19)
            }) {
                return Some(token.into());
            }
        }
        #[cfg(target_os = "macos")]
        if let Some((_, _, token)) = crate::darwin_process::DarwinParent::runtime_info(pid) {
            return Some(token);
        }
        None
    }
}
