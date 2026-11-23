//! owner: process status capture; allowed imports: std process, IO, threads and time.
//! forbidden imports: shell, repository policy, writes.
//! callers/tests: read_process, WikimapSearch and read_process_tests.
//! verification: raw pipe capture, status and bounded deadlines.
use std::io::Read;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::{Duration, Instant};

const MAX_NAP: Duration = Duration::from_millis(2);

pub(crate) fn capture_status(
    command: &mut Command,
    timeout: Duration,
    limit: Option<u64>,
) -> Result<Option<(Vec<u8>, Vec<u8>, ExitStatus)>, ()> {
    let mut child = match command
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
        read_pipe(pipe, true, sender.clone(), limit);
    }
    if let Some(pipe) = child.stderr.take() {
        read_pipe(pipe, false, sender.clone(), limit);
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
    Ok(Some((stdout, stderr, status)))
}

fn read_pipe<R: Read + Send + 'static>(
    mut pipe: R,
    stdout: bool,
    sender: Sender<(bool, std::io::Result<Vec<u8>>)>,
    limit: Option<u64>,
) {
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = match limit {
            None => pipe.read_to_end(&mut bytes).map(|_| bytes),
            Some(limit) => pipe
                .take(limit + 1)
                .read_to_end(&mut bytes)
                .and_then(|size| {
                    if size as u64 <= limit {
                        Ok(bytes)
                    } else {
                        Err(std::io::ErrorKind::InvalidData.into())
                    }
                }),
        };
        let _ = sender.send((stdout, result));
    });
}
