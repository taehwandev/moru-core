//! Preserve one raw callback input when a native proof cannot decide.
use std::{
    ffi::OsString,
    io::Write,
    os::unix::process::ExitStatusExt,
    process::{Command, Stdio},
};

pub(crate) struct CallbackReplay;

impl CallbackReplay {
    pub(crate) fn python(launcher: &OsString, args: &[OsString], raw: &[u8]) -> i32 {
        let child = Command::new("python3")
            .arg(launcher)
            .args(args)
            .stdin(Stdio::piped())
            .spawn();
        let mut child = match child {
            Ok(child) => child,
            Err(error) => {
                eprintln!("moru-native-launcher: Python compatibility path unavailable: {error}");
                return 127;
            }
        };
        if let Some(mut pipe) = child.stdin.take() {
            let _ = pipe.write_all(raw);
        }
        match child.wait() {
            Ok(status) => status
                .code()
                .unwrap_or_else(|| 128 + status.signal().unwrap_or(1)),
            Err(_) => 1,
        }
    }
}
