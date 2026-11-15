//! owner: DispatchGuardian, the already-admitted worker's private lifetime boundary;
//! allowed imports: command/process/receipt siblings, existing JSON, std and libc;
//! forbidden imports: admission, scheduler policy, providers, fallback and retries;
//! callers/tests: verified dispatch selection; sibling and parent owned-process tests;
//! verification: offline debug tests and immutable Python receipt/lifetime parity.
use crate::python_json::Value;
use std::{ffi::OsString, io, path::Path};

mod command;
mod process;
mod receipt;

const LIMIT: usize = 2 * 1024 * 1024;
pub(crate) struct DispatchGuardian;

impl DispatchGuardian {
    pub(crate) fn run(guardian: &OsString, args: &[OsString]) -> i32 {
        let result = match args {
            [mode, path] if mode == "--dispatch-guardian" && Path::new(guardian).is_absolute() => {
                Self::guard(guardian, Path::new(path))
            }
            [mode] if mode == "--dispatch-exec-gate" => Self::gate(),
            _ => Err(Self::invalid()),
        };
        result.unwrap_or(125)
    }

    fn guard(guardian: &OsString, path: &Path) -> io::Result<i32> {
        let Some(request) = Self::message(std::io::stdin().lock())? else {
            return Ok(130);
        };
        let (command, environment) = Self::request(&request)?;
        let state = Self::read_receipt(path)?;
        if Self::parent_closed(0)? {
            Self::save_receipt(path, &state, "interrupted", Some(130))?;
            return Ok(130);
        }
        let mut child = Self::spawn_gate(guardian, &environment)?;
        // Every path after spawn closes the gate and reaps its own group.
        let outcome = (|| {
            Self::save_receipt(path, &state, "running", None)?;
            if Self::parent_closed(0)? {
                return Ok(None);
            }
            Self::release(&mut child, &command)?;
            Self::observe(&mut child)
        })();
        drop(child.stdin.take());
        let final_status = Self::stop(&mut child);
        let observed = outcome?;
        let (phase, code) = match observed {
            None => ("interrupted", 130),
            Some(status) => ("finished", Self::exit_code(status)),
        };
        final_status?;
        Self::save_receipt(path, &state, phase, Some(code))?;
        Ok(code)
    }

    fn invalid() -> io::Error {
        io::Error::from_raw_os_error(libc::EINVAL)
    }

    fn command(value: &Value) -> io::Result<Vec<String>> {
        let command = value.as_array().ok_or_else(Self::invalid)?;
        if command.is_empty() {
            return Err(Self::invalid());
        }
        command
            .iter()
            .map(|item| {
                item.as_str()
                    .filter(|text| !text.contains('\0'))
                    .map(str::to_owned)
                    .ok_or_else(Self::invalid)
            })
            .collect()
    }
}
