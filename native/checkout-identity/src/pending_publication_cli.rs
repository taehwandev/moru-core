//! Owner: read-only pending-publication launcher status. Allowed: bound receipt
//! and bounded continuation reads. Forbidden: settlement, writes, Git and
//! interpreting an untrusted packet as an admitted action.

use crate::{
    pending_publication_receipt::PendingPublicationReceipt,
    pending_publication_status::PendingPublicationStatus, pretool_guard::CallbackGuard,
    python_encoding::PythonEncoding,
};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    env,
    ffi::OsString,
    io::{self, ErrorKind, Write},
    path::{Path, PathBuf},
};

pub(crate) struct PendingPublicationCli;

impl PendingPublicationCli {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if env::var_os("MORU_LAUNCHER_BACKEND").is_some_and(|mode| mode != "auto" && mode != "rust")
            || CallbackGuard::root(launcher, "pending-publication").is_none()
            || !PythonEncoding::utf8()
        {
            crate::exec_python(launcher, args);
        }
        let Some(text) = Self::status(args) else {
            crate::exec_python(launcher, args);
        };
        let mut output = io::stdout().lock();
        i32::from(
            writeln!(output, "{text}")
                .and_then(|_| output.flush())
                .is_err(),
        )
    }

    fn status(args: &[OsString]) -> Option<String> {
        let [_, action, first_flag, first_value, second_flag, second_value] = args else {
            return None;
        };
        if action != "status"
            || [first_value, second_value].iter().any(|v| {
                v.to_str()
                    .is_none_or(|v| v.is_empty() || v.starts_with('-'))
            })
        {
            return None;
        }
        let (project, evidence) = match (first_flag.to_str()?, second_flag.to_str()?) {
            ("--project", "--evidence") => (first_value, second_value),
            ("--evidence", "--project") => (second_value, first_value),
            _ => return None,
        };
        let project = Path::new(project).canonicalize().ok()?;
        let evidence: PathBuf = env::current_dir()
            .ok()?
            .join(evidence)
            .components()
            .collect();
        let run_id = evidence.parent()?.file_name()?;
        let packet = project
            .join(".moru")
            .join("runs")
            .join(run_id)
            .join("continuation.json");
        let possible = Self::possible_checkpoints(&packet)?;
        let receipt = PendingPublicationReceipt::probe(&json!({"evidence": evidence.to_str()?}))?;
        let rows: HashSet<_> = receipt
            .get("record")?
            .get("items")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|item| item.get("checkpoint")?.as_str())
            .collect();
        if possible.iter().any(|name| !rows.contains(name.as_str())) {
            return None;
        }

        // Admitting any subset of already recorded names cannot change the
        // outstanding list. Trust is still required to add any other name.
        let owed = PendingPublicationStatus::outstanding(&receipt, &[])?;
        Some(if owed.is_empty() {
            "no pending publication".into()
        } else {
            PendingPublicationStatus::reason(&owed)
        })
    }

    fn possible_checkpoints(packet: &Path) -> Option<Vec<String>> {
        let bytes = match PendingPublicationReceipt::read(packet, 256 * 1024)? {
            Ok(bytes) => bytes,
            Err(ErrorKind::NotFound) => return Some(Vec::new()),
            Err(_) => return None,
        };
        let packet: Value = serde_json::from_slice(&bytes).ok()?;
        let work = packet.get("work")?.as_object()?;
        let remaining = work.get("remaining_work")?.as_array()?;
        Some(
            remaining
                .iter()
                .filter_map(|item| item.get("checkpoint")?.as_str())
                .filter(|name| PendingPublicationReceipt::checkpoint(name))
                .map(str::to_owned)
                .collect(),
        )
    }
}
