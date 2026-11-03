//! Owner: empty-inbox mailbox status CLI and exact text/JSON output.
//! Allowed: std and existing source, filesystem, repository and status readers.
//! Forbidden: send/receive, packet interpretation, state writes and authority.
//! Callers/tests: launcher_main; native mailbox-status and transported smoke.
use crate::{
    cards_identity::CardRepository, discovery_fs::DiscoveryFs as Fs,
    mailbox_status_state::MailboxStatusState as Status, pretool_guard::CallbackGuard,
    statusline::Renderer,
};
use std::{env, ffi::OsString, io::Write, path::PathBuf};

pub(crate) struct MailboxStatusProcess;

impl MailboxStatusProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(text) = snapshot(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        match std::io::stdout().write_all(text.as_bytes()) {
            Ok(()) => 0,
            Err(_) => 1,
        }
    }
}

fn snapshot(launcher: &OsString, args: &[OsString]) -> Option<String> {
    let mut words = args.iter().map(|v| v.to_str());
    if words.next()?? != "status" {
        return None;
    }
    let (mut project, mut runtime, mut json) = (None, None, false);
    while let Some(word) = words.next() {
        match word? {
            "--project" if project.is_none() => project = Some(PathBuf::from(words.next()??)),
            "--runtime" if runtime.is_none() => runtime = Some(words.next()??),
            "--json" if !json => json = true,
            _ => return None,
        }
    }
    let runtime = match runtime? {
        "agy" | "antigravity" => "antigravity",
        value @ ("claude" | "codex") => value,
        _ => return None,
    };
    CallbackGuard::root(launcher, "git")?;
    let cwd = env::current_dir().ok()?;
    let project = match project {
        Some(path) => Fs::resolve(&Fs::expand(&path)?)?,
        None => {
            let cwd = Fs::resolve(&cwd)?;
            cwd.ancestors()
                .find(|path| path.join(".git").exists())?
                .to_owned()
        }
    };
    if !project.is_dir() {
        return None;
    }
    let home = PathBuf::from(env::var_os("HOME")?);
    let raw = match env::var("MORU_STATE_HOME") {
        Ok(value) if !Renderer::strip(&value).is_empty() => PathBuf::from(Renderer::strip(&value)),
        Err(env::VarError::NotUnicode(_)) => return None,
        _ => home.join(".moru"),
    };
    let expanded = Fs::expand(&raw)?;
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        cwd.join(expanded)
    };
    let state = Fs::resolve(absolute.parent()?)?.join(absolute.file_name()?);
    let legacy = Status::legacy(&project, runtime)?;
    let repository = CardRepository::key(&project)?;
    let acked = legacy + Status::reference(&state, &repository, runtime)?;
    Some(if json {
        format!("{{\"acked\": {acked}, \"expired\": 0, \"pending\": 0, \"rejected\": 0, \"runtime\": \"{runtime}\"}}\n")
    } else {
        format!("{runtime}: pending=0 expired=0 acked={acked} rejected=0\n")
    })
}
