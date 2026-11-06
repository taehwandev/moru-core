//! Native next CLI and read-only advice with supported bound ledgers.
//! Imports: std, existing source guard, CLI, session and verification owners. No state writes.
#[path = "next_advice.rs"]
mod advice;
#[path = "next_cli.rs"]
mod cli;
#[path = "next_ledger.rs"]
mod ledger;
#[path = "next_session.rs"]
mod session;
use crate::{next_verification::Verification, pretool_guard::CallbackGuard};
use std::{env, ffi::OsString, io::Write, path::Path};
pub(crate) struct NextProcess;
impl NextProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some((code, text, stderr)) = execute(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        let written = if stderr {
            std::io::stderr().write_all(text.as_bytes())
        } else {
            std::io::stdout().write_all(text.as_bytes())
        };
        if written.is_ok() {
            code
        } else {
            1
        }
    }
}
fn execute(launcher: &OsString, args: &[OsString]) -> Option<(i32, String, bool)> {
    let core = CallbackGuard::root(launcher, "git")?;
    let mut parsed = cli::NextCli::parse(args, &env::current_dir().ok()?)?;
    if let Some(exit) = parsed.exit {
        if !cli::NextCli::plain_exit(exit.2) {
            return None;
        }
        return Some(exit);
    }
    let home = env::var_os("HOME")?;
    let home = Path::new(&home);
    if home.canonicalize().ok()?.as_os_str() != home.as_os_str() {
        return None;
    }
    if parsed.project.as_os_str().is_empty() {
        parsed.project = env::current_dir().ok()?;
    }
    if parsed.project == Path::new("~") {
        parsed.project = home.to_owned();
    } else if parsed.project.to_str()?.starts_with("~/") {
        parsed.project = home.join(&parsed.project.to_str()?[2..]);
    } else if parsed.project.to_str()?.starts_with('~') {
        return None;
    }
    let project = parsed.project.canonicalize().ok()?;
    if !project.is_dir() {
        return None;
    }
    let explicit = match parsed.evidence {
        Some(path) => match std::fs::metadata(&path) {
            Ok(meta) if meta.is_file() => Some(path.canonicalize().ok()?),
            Ok(_) => None,
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory
                ) =>
            {
                None
            }
            Err(_) => return None,
        },
        None => None,
    };
    let evidence = match explicit {
        Some(path) => Some(path),
        None => session::NextSession::discover(&project)?,
    };
    let verification = Verification::discover(&project)?;
    if let Some(evidence) = evidence {
        return Some((
            0,
            selected(&project, &evidence, home, &parsed.format, &verification)?,
            false,
        ));
    }
    let copyable = format!(
        "{} start --project {} --rules {} --command <route> --request \"<USER_REQUEST>\" \
         --intent <safe_slug> --target-summary \"<bounded target>\"",
        home.join(".moru/bin/moru-hook").to_str()?,
        project.to_str()?,
        core.to_str()?
    );
    Some((
        0,
        render(project.to_str()?, &copyable, &verification, &parsed.format),
        false,
    ))
}
fn selected(
    project: &Path,
    evidence: &Path,
    home: &Path,
    format: &str,
    verification: &Verification,
) -> Option<String> {
    if evidence.file_name()?.to_str()?.ends_with('.') {
        return None;
    }
    let preflight_bytes = std::fs::read(&evidence).ok()?;
    let preflight =
        crate::python_json::PythonJson::parse(std::str::from_utf8(&preflight_bytes).ok()?)?;
    let ledger = evidence
        .parent()?
        .join(if evidence.file_name()? == "preflight.json" {
            "gate-evidence.json".to_string()
        } else {
            format!("{}-gate-evidence.json", evidence.file_stem()?.to_str()?)
        });
    let recorded = ledger::NextLedger::read(&evidence, &ledger, &preflight, &preflight_bytes)?;
    advice::NextAdvice::render(
        &project,
        &evidence,
        &preflight,
        &verification,
        format,
        &home.join(".moru/bin/moru-hook"),
        &recorded,
    )
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
