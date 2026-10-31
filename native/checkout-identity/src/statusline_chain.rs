//! Owner: one configured shell chain, with a two-second total deadline.
//! Imports: std + pure strip/newline helpers; no provider or repository reads.
use crate::statusline::Renderer;
use crate::statusline_process::StatuslineProcess;
use std::io::{Read, Write};
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

pub(crate) struct Chain;

impl Chain {
    pub(crate) fn run(command: &str, input: String) -> Result<String, ()> {
        if Renderer::strip(command).is_empty() {
            return Ok(String::new());
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        let Ok(mut child) = Command::new("/bin/sh")
            .args(["-c", command])
            .process_group(0)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        else {
            return Ok(String::new());
        };
        let group = child.id() as i32;
        let (tx, rx) = mpsc::channel();
        let mut stdin = child.stdin.take().ok_or(())?;
        let writer = tx.clone();
        thread::spawn(move || {
            let _ = stdin.write_all(input.as_bytes()); // BrokenPipe is ignored by communicate.
            drop(stdin);
            let _ = writer.send((0, Ok(Vec::new())));
        });
        Self::read(child.stdout.take().ok_or(())?, 1, tx.clone());
        Self::read(child.stderr.take().ok_or(())?, 2, tx.clone());
        drop(tx);
        let mut output = [Vec::new(), Vec::new(), Vec::new()];
        for _ in 0..3 {
            match rx.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                Ok((index, Ok(bytes))) => output[index] = bytes,
                _ => {
                    Self::kill_group(group);
                    let _ = child.wait();
                    return Ok(String::new());
                }
            }
        }
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break, // Nonzero child status still retains stdout.
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(1)),
                _ => {
                    Self::kill_group(group);
                    let _ = child.wait();
                    return Ok(String::new());
                }
            }
        }
        std::str::from_utf8(&output[2]).map_err(|_| ())?;
        let text = std::str::from_utf8(&output[1]).map_err(|_| ())?;
        Ok(StatuslineProcess::newlines(text))
    }

    fn read<R: Read + Send + 'static>(
        mut pipe: R,
        index: usize,
        sender: mpsc::Sender<(usize, std::io::Result<Vec<u8>>)>,
    ) {
        thread::spawn(move || {
            let mut bytes = Vec::new();
            let result = pipe.read_to_end(&mut bytes).map(|_| bytes);
            let _ = sender.send((index, result));
        });
    }

    fn kill_group(group: i32) {
        // process_group(0) made this task's child the leader of its own group.
        // POSIX kill with a negative PID affects only that group, including a
        // descendant holding a pipe after its shell exits. No user group is used.
        unsafe extern "C" {
            fn kill(pid: i32, signal: i32) -> i32;
        }
        if group > 0 {
            unsafe {
                kill(-group, 9);
            }
        }
    }
}
