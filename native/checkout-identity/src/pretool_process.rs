//! Native plain-query callback; all other decisions remain in the Python owner.
use serde_json::Value;
use std::{
    env,
    ffi::OsString,
    io::{self, Read, Write},
    os::unix::process::ExitStatusExt,
    path::Path,
    process::{Command, Stdio},
};

pub(crate) struct PretoolProcess;

impl PretoolProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 1 {
            crate::exec_python(launcher, args);
        }
        let mut raw = Vec::new();
        if io::stdin().read_to_end(&mut raw).is_err() {
            return Self::python(launcher, args, &raw);
        }
        if Self::plain(launcher, args, &raw) {
            0
        } else {
            Self::python(launcher, args, &raw)
        }
    }

    fn plain(launcher: &OsString, args: &[OsString], raw: &[u8]) -> bool {
        let Ok(payload) = serde_json::from_slice::<Value>(raw) else {
            return false;
        };
        if payload.get("tool_name").and_then(Value::as_str) != Some("Bash") {
            return false;
        }
        let Some(cwd) = payload.get("cwd").and_then(Value::as_str) else {
            return false;
        };
        if !Path::new(cwd).is_absolute() || !Path::new(cwd).canonicalize().is_ok_and(|p| p.is_dir())
        {
            return false;
        }
        let Some(command) = payload
            .get("tool_input")
            .and_then(|v| v.get("command"))
            .and_then(Value::as_str)
        else {
            return false;
        };
        let Some(executable) = crate::pretool_query::executable(command) else {
            return false;
        };
        let codex = args[0] == "codex-pretool-gate"
            || env::var("MORU_PRETOOL_RUNTIME").is_ok_and(|s| {
                crate::statusline::Renderer::strip(&s).eq_ignore_ascii_case("codex")
            });
        crate::pretool_guard::ready(launcher, executable)
            && (!codex || crate::pretool_transcript::safe(&payload))
    }

    fn python(launcher: &OsString, args: &[OsString], raw: &[u8]) -> i32 {
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
