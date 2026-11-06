//! Read-only Git: two-second text reads and ten-second raw EvidenceInputs listings.

use crate::{read_process::capture_raw, text::Text};
use std::process::{Command, Stdio};
use std::time::Duration;

const TIMEOUT: Duration = Duration::from_secs(2);

pub(crate) struct GitRead;

impl GitRead {
    pub(crate) fn run(root: &str, args: &[&str]) -> Result<Option<String>, ()> {
        capture(Command::new("git").arg("-C").arg(root).args(args))
    }

    /// Raw UTF-8 listing for EvidenceInputs; stderr bytes are deliberately ignored.
    /// None is runner uncertainty; Some(Err) is a deterministic capture failure.
    #[allow(dead_code)]
    pub(crate) fn input_paths(root: &std::path::Path) -> Option<Result<String, ()>> {
        let (stdout, _, success) = capture_raw(
            Command::new("git")
                .args([
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ])
                .current_dir(root)
                .stdin(Stdio::null()),
            Duration::from_secs(10),
        )
        .ok()??;
        Some(if success {
            String::from_utf8(stdout).map_err(|_| ())
        } else {
            Err(())
        })
    }

    #[allow(dead_code)] // Used by the launcher crate, not the identity library.
    pub(crate) fn status(root: &str) -> Option<String> {
        capture(
            Command::new("git")
                .args(["status", "--porcelain", "--untracked-files=all"])
                .current_dir(root),
        )
        .ok()
        .flatten()
    }
}

fn capture(command: &mut Command) -> Result<Option<String>, ()> {
    let Some((stdout, stderr, success)) = capture_raw(command.stdin(Stdio::null()), TIMEOUT)?
    else {
        return Ok(None);
    };
    if std::str::from_utf8(&stderr).is_err() {
        return Err(());
    }
    let stdout = String::from_utf8(stdout).map_err(|_| ())?;
    if !success {
        return Ok(None);
    }
    Ok(Some(Text::universal_newlines(&stdout)))
}

#[cfg(test)]
#[path = "gitrun_tests.rs"]
mod tests;
