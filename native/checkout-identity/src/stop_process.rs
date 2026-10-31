//! Native Stop only proves a silent no-op; current Python owns every transition.
use crate::{
    callback_replay::CallbackReplay, mailbox_state::Mailboxes, pretool_guard::CallbackGuard,
    stop_state::StopState,
};
use serde_json::Value;
use std::{
    env,
    ffi::OsString,
    io::{self, Read},
    path::{Path, PathBuf},
};

pub(crate) struct StopProcess;

impl StopProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 1 {
            crate::exec_python(launcher, args);
        }
        let mut raw = Vec::new();
        if io::stdin().read_to_end(&mut raw).is_ok() && Self::quiet(launcher, args, &raw).is_some()
        {
            0
        } else {
            CallbackReplay::python(launcher, args, &raw)
        }
    }

    fn quiet(launcher: &OsString, args: &[OsString], raw: &[u8]) -> Option<()> {
        if raw.len() > 65536 {
            return None;
        }
        let payload: Value = serde_json::from_slice(raw).ok()?;
        let session = payload.get("session_id")?.as_str()?;
        if session.is_empty()
            || session.len() > 128
            || !session
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return None;
        }
        let cwd = Path::new(payload.get("cwd")?.as_str()?);
        if !cwd.is_absolute() {
            return None;
        }
        let cwd = cwd.canonicalize().ok()?;
        if !cwd.is_dir() {
            return None;
        }
        let project = cwd.ancestors().find(|p| p.join(".git").exists())?;
        StopState::candidate(project)?;
        CallbackGuard::root(launcher, "git")?;
        let runtime = if args[0] == "claude-stop-gate" {
            "claude"
        } else {
            "codex"
        };
        let mut mailbox = Mailboxes::quiet(project, runtime)?;
        let gate = if runtime == "claude" {
            "MORU_CLAUDE_STOP_GATE"
        } else {
            "MORU_CODEX_STOP_GATE"
        };
        if env::var(gate).is_ok_and(|s| crate::statusline::Renderer::strip(&s) == "0") {
            return Some(());
        }
        mailbox.tasks_empty()?;
        let state = env::var("MORU_STATE_HOME")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(|s| PathBuf::from(crate::statusline::Renderer::strip(&s)))
            .unwrap_or(PathBuf::from(env::var_os("HOME")?).join(".moru"));
        StopState::quiet(project, &state, runtime, session)
    }
}
