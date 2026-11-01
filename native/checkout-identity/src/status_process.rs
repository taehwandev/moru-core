//! Native basic status ingress; unsupported/uncertain paths exec the Python owner.
//! Owner: prepared status dispatch. Allowed: source guard, status state/snapshot, std.
//! Forbidden: state initialization, lifecycle policy, trends and external work.
//! Callers/tests: native launcher; generated native status and consumer tests.
//! Verification: canonical output and lock/contention/source/CLI fallback parity.
use crate::{
    pretool_guard::CallbackGuard, status_snapshot::StatusSnapshot, status_state::StatusState,
};
use std::{env, ffi::OsString, io::Write, path::PathBuf};

pub(crate) struct StatusProcess;

impl StatusProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(text) = snapshot(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        if std::io::stdout().write_all(text.as_bytes()).is_ok() {
            0
        } else {
            1
        }
    }
}

fn snapshot(launcher: &OsString, args: &[OsString]) -> Option<String> {
    let words = args
        .iter()
        .map(|s| s.to_str())
        .collect::<Option<Vec<_>>>()?;
    let (project, validated) = match words.as_slice() {
        [] => (env::current_dir().ok()?, false),
        ["--validate"] => (env::current_dir().ok()?, true),
        ["--project", path] => (PathBuf::from(path), false),
        ["--project", path, "--validate"] | ["--validate", "--project", path] => {
            (PathBuf::from(path), true)
        }
        _ => return None,
    };
    if !project.is_absolute() || !project.is_dir() {
        return None;
    }
    let project = project.canonicalize().ok()?;
    // Reject-only precheck. Fresh state is read again under locks after the
    // complete source scan; this cannot admit output or retain stale values.
    if !StatusSnapshot::supported(&StatusState::read(&project)?) {
        return None;
    }
    CallbackGuard::root(launcher, "agent-os-status")?;
    let captured = StatusSnapshot::capture_time()?;
    let values = StatusState::read(&project)?; // All locks released before render/fallback.
    let present = [
        project.join(".moru/run-registry.json").exists(),
        project.join(".moru/scheduler.json").exists(),
    ];
    StatusSnapshot::render(&values, &captured, present, validated)
}
