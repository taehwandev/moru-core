//! owner: existing RegistryRead read-only runs-prune command/report;
//! allowed imports: source/encoding guards, existing retention readers, std and JSON;
//! forbidden imports: deletion, locks, lifecycle mutation, providers or policy copies;
//! callers/tests: launcher runs-prune dispatch and sibling temp-FS report tests;
//! verification: offline native tests; parent original-Python process parity.
use super::RegistryRead;
use crate::{
    callback_state::LocalState, pretool_guard::CallbackGuard, python_encoding::PythonEncoding,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fmt::Write as _,
    fs,
    io::Write,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

impl RegistryRead {
    pub(crate) fn runs_prune(launcher: &OsString, args: &[OsString]) -> i32 {
        // Parse before target reads. Every apply/unsupported form replaces the
        // whole process, preserving the original stdin, argv, cwd and environment.
        let Some((policy, options)) = Self::retention_policy().and_then(|policy| {
            Self::retention_report_args(&args[1..], &policy).map(|options| (policy, options))
        }) else {
            crate::exec_python(launcher, args)
        };
        if !PythonEncoding::utf8() || CallbackGuard::root(launcher, "runs-prune").is_none() {
            crate::exec_python(launcher, args);
        }
        let Some(output) = Self::retention_report(&options, &policy) else {
            crate::exec_python(launcher, args);
        };
        let mut stdout = std::io::stdout().lock();
        if stdout
            .write_all(output.as_bytes())
            .and_then(|_| stdout.flush())
            .is_ok()
        {
            0
        } else {
            1
        }
    }

    pub(super) fn retention_report(options: &Value, policy: &Value) -> Option<String> {
        let project = Path::new(options["project"].as_str()?);
        // Existing readers require physical absolute paths. Preserve other
        // Pathlib spellings by deferring before producing any report output.
        if project.canonicalize().ok()?.to_str()? != options["project"].as_str()? {
            return None;
        }
        LocalState::safe_path(Path::new("/"), project)?;
        let state = project.join(policy["state_dir"].as_str()?);
        let directory = state.join(policy["runs_dir"].as_str()?);
        LocalState::safe_path(project, &directory)?;
        if !directory_kind(&directory)? {
            return Some(format!("no run directory at {}\n", directory.to_str()?));
        }
        let registry_path = state.join("run-registry.json");
        // A missing registry supports evidence-only reports. Every existing
        // file uses the original shared reader; its parser/I/O declines must
        // reach Python before output, even if the file subsequently disappears.
        let registry = if path_exists(&registry_path)? {
            Self::retention_states(&json!({"state_dir":state,
                "states":policy["run_states"], "int_digits":int_digits()?}))?
        } else {
            Value::Null
        };
        let uncertain = registry.is_null() && path_exists(&registry_path)?;
        let states = if registry.is_null() {
            Value::Null
        } else {
            let mut states = serde_json::Map::new();
            for row in registry.as_array()? {
                states.insert(row[0].as_str()?.to_owned(), row[1].clone());
            }
            Value::Object(states)
        };
        let moment = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_secs_f64();
        let plan = Self::retention_plan(&json!({"directory":directory,
            "registry_states":states, "registry_uncertain":uncertain,
            "protected":[], "cutoff":moment - options["abandoned_after_seconds"].as_u64()? as f64,
            "orphan_cutoff":moment - options["orphan_after_seconds"].as_u64()? as f64,
            "keep":options["keep"], "holding_states":policy["holding_states"],
            "settled_states":policy["settled_states"], "finished_phases":policy["finished_phases"],
            "int_digits":int_digits()?}))?;
        Self::retention_report_text(&directory, &plan)
    }
}

impl RegistryRead {
    fn retention_report_text(directory: &Path, plan: &Value) -> Option<String> {
        let mut output = format!("runs: {}\n", directory.to_str()?);
        let rows = |name: &str| plan.get(name)?.as_array();
        let (finished, unfinished, abandoned, orphaned) = (
            rows("finished")?,
            rows("unfinished")?,
            rows("abandoned")?,
            rows("orphaned")?,
        );
        writeln!(
            output,
            "finished: {}  unfinished: {}  abandoned: {}  orphaned: {}",
            finished.len(),
            unfinished.len(),
            abandoned.len(),
            orphaned.len()
        )
        .ok()?;
        let unclassified = rows("unclassified")?;
        if !unclassified.is_empty() {
            writeln!(
                output,
                "not named like a run id, never removed: {} ({} bytes)",
                unclassified.len(),
                Self::retention_report_bytes(directory, unclassified)?
            )
            .ok()?;
        }
        let removable = rows("removable")?;
        writeln!(
            output,
            "keeping the newest {} finished; removable: {}",
            rows("kept")?.len(),
            removable.len()
        )
        .ok()?;
        if !unfinished.is_empty() {
            output.push_str("unfinished runs are kept while they can still be resumed:\n");
            let mut remaining = 8 * 1024 * 1024;
            for name in unfinished.iter().take(5) {
                let name = name.as_str()?;
                let phase = Self::retention_phase(&directory.join(name), &mut remaining)?;
                writeln!(
                    output,
                    "    {name}  phase={}",
                    if phase.is_empty() {
                        "unreadable"
                    } else {
                        &phase
                    }
                )
                .ok()?;
            }
            if unfinished.len() > 5 {
                writeln!(output, "    ... and {} more", unfinished.len() - 5).ok()?;
            }
        }
        if removable.is_empty() {
            output.push_str("nothing to remove\n");
        } else {
            writeln!(
                output,
                "bytes to free: {}",
                Self::retention_report_bytes(directory, removable)?
            )
            .ok()?;
            output.push_str("report only; pass --apply to remove them\n");
        }
        Some(output)
    }

    fn retention_report_bytes(directory: &Path, names: &[Value]) -> Option<String> {
        let paths = names
            .iter()
            .map(|name| Some(json!(directory.join(name.as_str()?))))
            .collect::<Option<Vec<_>>>()?;
        Self::retention_bytes(&json!({"paths":paths}))?
            .as_str()
            .map(str::to_owned)
    }
}

fn int_digits() -> Option<u64> {
    option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
        .unwrap_or("0")
        .parse()
        .ok()
}

fn directory_kind(path: &Path) -> Option<bool> {
    match fs::metadata(path) {
        Ok(metadata) => Some(metadata.is_dir()),
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::EBADF | libc::ELOOP)
            ) =>
        {
            Some(false)
        }
        Err(_) => None,
    }
}

fn path_exists(path: &Path) -> Option<bool> {
    match fs::metadata(path) {
        Ok(_) => Some(true),
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::EBADF | libc::ELOOP)
            ) =>
        {
            Some(false)
        }
        Err(_) => None,
    }
}

#[cfg(test)]
#[path = "registry_retention_report_tests.rs"]
mod tests;
