//! owner: ProcessOwner; allowed imports: std, libc, Python text/JSON and Darwin ABI;
//! forbidden imports: writes, liveness signals, process spawning; callers/tests:
//! NextSession ambiguity selection; verification: owner/proc fixtures and live parity.
#[cfg(target_os = "macos")]
#[path = "next_owner_darwin.rs"]
mod darwin;
use crate::{python_json::Value, python_text::PythonText};
use std::fs;

pub(super) struct ProcessOwner {
    pid: u64,
    start_token: String,
}

impl ProcessOwner {
    /// Outer None requires Python's ps compatibility path; inner None means no owner.
    pub(super) fn current() -> Option<Option<Self>> {
        let leader = unsafe { libc::getsid(0) };
        if leader < 1 {
            return Some(None);
        }
        let parent = Self::parent(leader)?;
        let Some(pid) = Self::anchor(leader as i64, parent) else {
            return Some(None);
        };
        // Kernel pids are small; unusual proc data must not weaken int/float equality.
        if pid > (1u64 << 53) {
            return None;
        }
        let start_token = match fs::read(format!("/proc/{pid}/stat")) {
            Ok(bytes) => Self::token(&String::from_utf8_lossy(&bytes)),
            Err(_) => String::new(),
        };
        Some(Some(Self { pid, start_token }))
    }

    pub(super) fn matches(&self, value: Option<&Value>) -> bool {
        let Some(owner) = value.and_then(Value::as_object) else {
            return false;
        };
        if owner.len() != 2
            || owner.get("start_token").and_then(Value::as_str) != Some(&self.start_token)
        {
            return false;
        }
        match owner.get("pid") {
            Some(Value::Number(n)) => n.equals_u64(self.pid),
            Some(Value::Bool(v)) => u64::from(*v) == self.pid,
            _ => false,
        }
    }

    fn parent(leader: i32) -> Option<i64> {
        if let Ok(bytes) = fs::read(format!("/proc/{leader}/stat")) {
            if let Some(parent) = Self::parent_field(&String::from_utf8_lossy(&bytes)) {
                return parent.parse().ok();
            }
        }
        #[cfg(target_os = "macos")]
        {
            let parent = darwin::DarwinParent::read(leader);
            if parent != 0 {
                return Some(i64::from(parent));
            }
        }
        // Python next tries ps. Do not invent an empty owner when that may succeed.
        None
    }

    fn anchor(leader: i64, parent: i64) -> Option<u64> {
        let pid = if parent == 1 { leader } else { parent };
        (pid > 0).then_some(pid as u64)
    }

    fn fields(stat: &str) -> impl Iterator<Item = &str> {
        stat.rsplit_once(')')
            .map_or(stat, |(_, rest)| rest)
            .split(PythonText::whitespace)
            .filter(|s| !s.is_empty())
    }

    fn token(stat: &str) -> String {
        Self::fields(stat).nth(19).unwrap_or("").into()
    }

    fn parent_field(stat: &str) -> Option<String> {
        let text = Self::fields(stat).nth(1)?;
        let mut normalized = String::new();
        let mut previous_digit = false;
        let chars: Vec<char> = text.chars().collect();
        for (i, c) in chars.iter().copied().enumerate() {
            if i == 0 && matches!(c, '+' | '-') {
                normalized.push(c);
                continue;
            }
            if c == '_'
                && previous_digit
                && chars.get(i + 1).is_some_and(|c| PythonText::decimal(*c))
            {
                previous_digit = false;
                continue;
            }
            let digit = PythonText::decimal_value(c)?;
            normalized.push(char::from(b'0' + digit));
            previous_digit = true;
        }
        previous_digit.then_some(normalized)
    }
}

#[cfg(test)]
#[path = "next_process_owner_tests.rs"]
mod tests;
