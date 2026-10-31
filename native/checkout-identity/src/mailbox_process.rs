//! Quiet callbacks only. Delivery, acknowledgements and authority remain Python-owned.
use crate::{callback_replay::CallbackReplay, mailbox_state::Mailboxes};
use serde_json::Value;
use std::{
    ffi::OsString,
    io::{self, Read},
    path::Path,
};

pub(crate) struct MailboxProcess;

impl MailboxProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 4
            || args[2] != "--runtime"
            || !matches!(args[1].to_str(), Some("deliver" | "ack"))
            || !matches!(args[3].to_str(), Some("claude" | "codex"))
        {
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
        let session = crate::statusline::Renderer::strip(payload.get("session_id")?.as_str()?);
        if session.is_empty()
            || session.len() > 128
            || !session.is_ascii()
            || session.bytes().any(|b| b < 32 || b == 127)
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
        let root = crate::pretool_guard::CallbackGuard::root(launcher, "git")?;
        let runtime = args[3].to_str()?;
        let mailboxes = Mailboxes::quiet(project, runtime)?;
        if args[1] == "deliver" {
            mailboxes.prompt_ready(&root, runtime, session)?;
        }
        Some(())
    }
}
