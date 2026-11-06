//! Read-only Git: two-second text reads and ten-second raw EvidenceInputs listings.

use crate::text::Text;
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::{Duration, Instant};

const TIMEOUT: Duration = Duration::from_secs(2);
const MAX_NAP: Duration = Duration::from_millis(2);

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
                .current_dir(root),
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

// None covers runner uncertainty; exit status and raw pipes stay separate so
// each caller can preserve its reference decoding and failure behavior.
fn capture_raw(
    command: &mut Command,
    timeout: Duration,
) -> Result<Option<(Vec<u8>, Vec<u8>, bool)>, ()> {
    let mut child = match command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return Ok(None),
    };
    let deadline = Instant::now() + timeout;
    let (sender, receiver) = mpsc::channel();
    if let Some(pipe) = child.stdout.take() {
        read_pipe(pipe, true, sender.clone());
    }
    if let Some(pipe) = child.stderr.take() {
        read_pipe(pipe, false, sender.clone());
    }
    drop(sender);
    let mut nap = Duration::from_micros(50);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => {
                thread::sleep(nap);
                nap = (nap * 2).min(MAX_NAP);
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return Ok(None);
            }
        }
    };
    // A child can exit while its descendant still holds a pipe open. Joining
    // a blocking reader here would escape the per-call timeout entirely.
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    for _ in 0..2 {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let Ok((is_stdout, Ok(bytes))) = receiver.recv_timeout(remaining) else {
            return Ok(None);
        };
        if is_stdout {
            stdout = bytes;
        } else {
            stderr = bytes;
        }
    }
    Ok(Some((stdout, stderr, status.success())))
}

fn capture(command: &mut Command) -> Result<Option<String>, ()> {
    let Some((stdout, stderr, success)) = capture_raw(command, TIMEOUT)? else {
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

fn read_pipe<R: Read + Send + 'static>(
    mut pipe: R,
    stdout: bool,
    sender: Sender<(bool, std::io::Result<Vec<u8>>)>,
) {
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = pipe.read_to_end(&mut bytes).map(|_| bytes);
        let _ = sender.send((stdout, result));
    });
}
#[cfg(test)]
#[path = "gitrun_tests.rs"]
mod tests;
