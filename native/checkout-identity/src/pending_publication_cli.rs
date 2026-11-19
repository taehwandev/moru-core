//! Owner: pending-publication launcher status and local settlement. Allowed:
//! bound receipt operations, bounded continuation reads and read-only local Git.
//! Forbidden: Git mutations, remote/provider calls and granting authority.

use crate::{
    completion_process::pending_publication_settlement::LocalSettlement,
    pending_publication_receipt::PendingPublicationReceipt,
    pending_publication_status::PendingPublicationStatus, pretool_guard::CallbackGuard,
    python_encoding::PythonEncoding,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    env,
    ffi::OsString,
    fs::File,
    io::{self, ErrorKind, Read, Write},
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
        let response = match args.get(1).and_then(|value| value.to_str()) {
            Some("status") => Self::status(args).map(|text| (0, text)),
            Some("settle") => Self::settle(args),
            _ => None,
        };
        let Some((status, text)) = response else {
            crate::exec_python(launcher, args);
        };
        let mut output = io::stdout().lock();
        if writeln!(output, "{text}")
            .and_then(|_| output.flush())
            .is_err()
        {
            1
        } else {
            status
        }
    }

    fn settle(args: &[OsString]) -> Option<(i32, String)> {
        let [_, _, options @ ..] = args else {
            return None;
        };
        if options.len() != 6 {
            return None;
        }
        let (mut project, mut evidence, mut checkpoint) = (None, None, None);
        for pair in options.chunks_exact(2) {
            let value = pair[1].to_str()?;
            if value.is_empty() || value.starts_with('-') {
                return None;
            }
            match pair[0].to_str()? {
                "--project" if project.is_none() => project = Some(value),
                "--evidence" if evidence.is_none() => evidence = Some(value),
                "--checkpoint" if checkpoint.is_none() => checkpoint = Some(value),
                _ => return None,
            }
        }
        let checkpoint = checkpoint?;
        if !LocalSettlement::supports(checkpoint) {
            return None;
        }
        let project = Path::new(project?).canonicalize().ok()?;
        let evidence: PathBuf = env::current_dir()
            .ok()?
            .join(evidence?)
            .components()
            .collect();
        if evidence != evidence.canonicalize().ok()?
            || evidence.file_name()?.to_str()? != "preflight.json"
        {
            return None;
        }
        let run = evidence.parent()?;
        if run.parent()? != project.join(".moru/runs")
            || !PendingPublicationReceipt::is_id(run.file_name()?.to_str()?)
        {
            return None;
        }
        let evidence_text = evidence.to_str()?;
        let receipt = PendingPublicationReceipt::probe(&json!({"evidence": evidence_text}))?;
        let record = receipt.get("record")?;
        if record.is_null() {
            let problem = receipt.get("problem")?.as_str()?;
            return Some(Self::settle_failure(&format!(
                "no usable pending publication record for this run ({problem})"
            )));
        }
        let result = LocalSettlement::prepare(&json!({
            "project": project.to_str()?,
            "record": record,
            "checkpoint": checkpoint,
            "binding": {
                "state_dir": project.join(".moru").to_str()?,
                "evidence_key": format!("{:x}", Sha256::digest(evidence.strip_prefix(&project).ok()?.to_str()?.as_bytes())),
                "legacy_key": format!("{:x}", Sha256::digest(b".moru/preflight.json")),
            },
        }))?;
        let reason = result.get("reason")?.as_str()?;
        if !reason.is_empty() {
            return Some(Self::settle_failure(reason));
        }
        let mut entropy = [0u8; 16];
        File::open("/dev/urandom")
            .ok()?
            .read_exact(&mut entropy)
            .ok()?;
        let temporary: String = entropy.iter().map(|byte| format!("{byte:02x}")).collect();
        let stored = PendingPublicationReceipt::replace(&json!({
            "evidence": evidence_text, "record": result.get("record")?, "temporary": temporary,
        }))?;
        // A concrete replacement result is terminal. Never invoke Python after a write attempt.
        let outcome = match stored.get("error") {
            Some(Value::Null) => (0, "publication observation recorded".into()),
            error => Self::settle_failure(&format!(
                "observation could not be stored ({})",
                error.and_then(Value::as_str).unwrap_or("OSError")
            )),
        };
        Some(outcome)
    }

    fn settle_failure(reason: &str) -> (i32, String) {
        (2, format!("FAIL publication settle: {reason}"))
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
