//! Read-only git fallback: no shell, two-second timeout per call.

use crate::text::Text;
use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::{Duration, Instant};

const TIMEOUT: Duration = Duration::from_secs(2);
const MAX_NAP: Duration = Duration::from_millis(2);

/// Ok(None) covers a missing executable, timeout or nonzero exit, the cases
/// where the production code yields None or an empty string.
pub fn run(root: &str, args: &[&str]) -> Result<Option<String>, ()> {
    let mut child = match Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(_) => return Ok(None),
    };
    let deadline = Instant::now() + TIMEOUT;
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
    if std::str::from_utf8(&stderr).is_err() {
        return Err(());
    }
    let stdout = String::from_utf8(stdout).map_err(|_| ())?;
    if !status.success() {
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
