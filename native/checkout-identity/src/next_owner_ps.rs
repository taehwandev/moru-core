//! owner: PsParent; allowed imports: shared bounded capture, Python text, owner integer;
//! forbidden imports: writes, shell interpolation, environment mutation;
//! callers/tests: ProcessOwner; verification: stdout/status/decoding/integer boundaries.
use super::ProcessOwner;
use crate::{python_text::PythonText, read_process::capture_raw, text::Text};
use std::{env, process::Command, time::Duration};

pub(super) struct PsParent;
impl PsParent {
    pub(super) fn read(leader: i32) -> Option<i64> {
        // Python text=True follows its runtime encoding; locale guessing is unsafe.
        if env::var("PYTHONUTF8").ok().as_deref() != Some("1") {
            return None;
        }
        let captured = capture_raw(
            Command::new("ps").args(["-o", "ppid=", "-p", &leader.to_string()]),
            Duration::from_secs(5),
        );
        match captured {
            Ok(Some((stdout, stderr, _))) => Self::decode(&stdout, &stderr),
            // Python catches unavailable commands, pipe errors and timeout alike.
            _ => Some(0),
        }
    }

    fn decode(stdout: &[u8], stderr: &[u8]) -> Option<i64> {
        let (Ok(stdout), Ok(_)) = (std::str::from_utf8(stdout), std::str::from_utf8(stderr)) else {
            return Some(0);
        };
        let stdout = Text::universal_newlines(stdout);
        let text = stdout.trim_matches(PythonText::whitespace);
        if text.is_empty() {
            return Some(0);
        }
        let Some(integer) = ProcessOwner::integer(text) else {
            return Some(0);
        };
        // Preserve builder Python's decimal conversion limit, including leading zeroes.
        let limit = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(0);
        if limit != 0 && integer.bytes().filter(u8::is_ascii_digit).count() > limit {
            return Some(0);
        }
        // An arbitrary precision parent must defer rather than overflow or clamp.
        integer.parse().ok()
    }
}

#[cfg(test)]
#[path = "next_owner_ps_tests.rs"]
mod tests;
