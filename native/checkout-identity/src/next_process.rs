//! Quiet next advice plus explicit-evidence advice when no ledger exists.
//! Imports: std, existing guard/locks/terminal-state/Git readers. No state writes.
#[path = "next_advice.rs"]
mod advice;
use crate::next_verification::Verification;
use crate::{
    callback_state::LocalState as State, pretool_guard::CallbackGuard, stop_state::StopState,
};
use std::{env, ffi::OsString, fs::File, io::Write, path::Path};

pub(crate) struct NextProcess;

impl NextProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(text) = quiet(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        match std::io::stdout().write_all(text.as_bytes()) {
            Ok(()) => 0,
            Err(_) => 1,
        }
    }
}

fn quiet(launcher: &OsString, args: &[OsString]) -> Option<String> {
    if args.iter().any(|a| {
        a.to_str()
            .is_some_and(|s| s == "--evidence" || s.starts_with("--evidence="))
    }) {
        return explicit(launcher, args);
    }
    let cwd = env::current_dir().ok()?;
    let (project, format) = arguments(args, &cwd)?;
    if !project.is_absolute() || !project.is_dir() {
        return None;
    }
    let project = project.canonicalize().ok()?;
    let home = env::var_os("HOME")?;
    let home = Path::new(&home);
    if home.canonicalize().ok()?.as_os_str() != home.as_os_str()
        || env::var_os("MORU_WORKER_EVIDENCE").is_some()
    {
        return None;
    }
    // This precheck only rejects. Recheck after source validation under locks.
    if has_session()? {
        StopState::candidate(&project)?;
    }
    let core = CallbackGuard::root(launcher, "git")?;
    drop(inactive(&project)?); // Python also releases registry locks before Git.
    let verification = Verification::discover(&project)?;
    let copyable = format!(
        "{} start --project {} --rules {} --command <route> --request \"<USER_REQUEST>\" \
         --intent <safe_slug> --target-summary \"<bounded target>\"",
        home.join(".moru/bin/moru-hook").to_str()?,
        project.to_str()?,
        core.to_str()?
    );
    Some(render(project.to_str()?, &copyable, &verification, format))
}

fn explicit(launcher: &OsString, args: &[OsString]) -> Option<String> {
    let mut project = env::current_dir().ok()?;
    let mut evidence = None;
    let mut format = "markdown";
    let mut i = 0;
    while i < args.len() {
        let word = args[i].to_str()?;
        let (key, inline) = word
            .split_once('=')
            .map_or((word, None), |(k, v)| (k, Some(v)));
        if !matches!(key, "--project" | "--evidence" | "--format") {
            return None;
        }
        let value = if let Some(v) = inline {
            v
        } else {
            i += 1;
            let value = args.get(i)?.to_str()?;
            if value.starts_with('-') {
                return None;
            }
            value
        };
        match key {
            "--project" => project = Path::new(value).to_owned(),
            "--evidence" => evidence = Some(Path::new(value).to_owned()),
            "--format" if matches!(value, "json" | "markdown") => format = value,
            _ => return None,
        }
        i += 1;
    }
    let home = env::var_os("HOME")?;
    let home = Path::new(&home);
    if home.canonicalize().ok()?.as_os_str() != home.as_os_str() {
        return None;
    }
    if project == Path::new("~") {
        project = home.to_owned();
    } else if project.to_str()?.starts_with("~/") {
        project = home.join(&project.to_str()?[2..]);
    } else if project.to_str()?.starts_with('~') {
        return None;
    }
    let project = project.canonicalize().ok()?;
    if !project.is_dir() {
        return None;
    }
    let evidence = evidence?;
    if !evidence.is_file() {
        return None;
    }
    let evidence = evidence.canonicalize().ok()?;
    // pathlib's trailing-dot stem semantics changed between builder Python versions.
    if evidence.file_name()?.to_str()?.ends_with('.') {
        return None;
    }
    CallbackGuard::root(launcher, "git")?;
    // Reference explicit evidence bypasses registry/session selection and its locks.
    let verification = Verification::discover(&project)?;
    let preflight =
        crate::python_json::PythonJson::parse(&std::fs::read_to_string(&evidence).ok()?)?;
    let ledger = evidence
        .parent()?
        .join(if evidence.file_name()? == "preflight.json" {
            "gate-evidence.json".to_string()
        } else {
            format!("{}-gate-evidence.json", evidence.file_stem()?.to_str()?)
        });
    match std::fs::symlink_metadata(ledger) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        _ => return None,
    }
    advice::NextAdvice::render(
        &project,
        &evidence,
        &preflight,
        &verification,
        format,
        &home.join(".moru/bin/moru-hook"),
    )
}

fn arguments<'a>(args: &'a [OsString], cwd: &Path) -> Option<(std::path::PathBuf, &'a str)> {
    let words: Vec<&str> = args.iter().map(|v| v.to_str()).collect::<Option<_>>()?;
    match words.as_slice() {
        [] => Some((cwd.to_owned(), "markdown")),
        ["--format", format @ ("json" | "markdown")] => Some((cwd.to_owned(), *format)),
        ["--project", project] => Some((Path::new(project).to_owned(), "markdown")),
        ["--project", project, "--format", format @ ("json" | "markdown")] => {
            Some((Path::new(project).to_owned(), *format))
        }
        _ => None,
    }
}

fn has_session() -> Option<bool> {
    let mut found = false;
    for key in [
        "CLAUDE_CODE_SESSION_ID",
        "CODEX_THREAD_ID",
        "ANTIGRAVITY_CONVERSATION_ID",
    ] {
        match env::var(key) {
            Ok(value) => found |= !crate::statusline::Renderer::strip(&value).is_empty(),
            Err(env::VarError::NotPresent) => {}
            Err(_) => return None,
        }
    }
    Some(found)
}

fn inactive(project: &Path) -> Option<Vec<File>> {
    if !has_session()? {
        return Some(Vec::new());
    }
    let local = project.join(".moru");
    State::safe_path(project, &local)?;
    if State::absent_dir(&local)? {
        return Some(Vec::new());
    }
    for marker in ["moru-root", "projects.json", "bin/moru-hook"] {
        if local.join(marker).exists() {
            return None;
        }
    }
    let locks = vec![
        State::lock(&local.join(".state.lock.lock"))?,
        State::lock(&local.join(".run-registry.json.lock"))?,
    ];
    StopState::candidate(project)?;
    Some(locks)
}

fn render(project: &str, copyable: &str, verification: &Verification, format: &str) -> String {
    if format == "json" {
        let quote = |text: &str| serde_json::to_string(text).unwrap();
        return format!(
            "{{\"copyable_command\": {}, \"next_step\": \"start\", \
             \"project\": {}, \"status\": \"no_active_run\", \
             \"verification\": {}}}\n",
            quote(copyable),
            quote(project),
            verification.json()
        );
    }
    let mut lines = vec![
        "SUCCESS next (no_active_run)".to_owned(),
        format!("- project: {project}"),
        "- next step: start".to_owned(),
        format!("- copyable command: {copyable}"),
    ];
    if !verification.commands.is_empty() {
        lines.push("- suggested fast verification for changed files:".to_owned());
        lines.extend(verification.commands.iter().map(|s| format!("  * {s}")));
    }
    lines.join("\n") + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closed_cli_keeps_evidence_and_unknown_flags_with_python() {
        let cwd = Path::new("/synthetic");
        for words in [
            vec![],
            vec!["--format", "json"],
            vec!["--project", "/other"],
            vec!["--project", "/other", "--format", "markdown"],
        ] {
            let args: Vec<OsString> = words.iter().map(OsString::from).collect();
            assert!(arguments(&args, cwd).is_some());
        }
        for words in [
            vec!["--evidence", "/preflight.json"],
            vec!["--help"],
            vec!["--format", "json", "--project", "/other"],
            vec!["--format", "yaml"],
            vec!["--project"],
            vec!["--project", "/other", "--unknown"],
        ] {
            let args: Vec<OsString> = words.iter().map(OsString::from).collect();
            assert!(arguments(&args, cwd).is_none());
        }
    }

    #[test]
    fn json_preserves_python_spacing_unicode_and_empty_verification() {
        assert_eq!(
            render("/한글", "start", &Verification::default(), "json"),
            "{\"copyable_command\": \"start\", \"next_step\": \"start\", \
             \"project\": \"/한글\", \"status\": \"no_active_run\", \
             \"verification\": {\"changed_paths\": [], \"matched_test_modules\": [], \
             \"suggested_commands\": []}}\n"
        );
    }

    #[test]
    fn markdown_preserves_empty_verification_guidance() {
        assert_eq!(
            render("/project", "start", &Verification::default(), "markdown"),
            "SUCCESS next (no_active_run)\n- project: /project\n- next step: start\n\
             - copyable command: start\n"
        );
    }
}
