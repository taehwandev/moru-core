//! Owner: native read-query ingress, including one literal cd and output pipe.
//! Allowed: existing query/source/transcript guards, std/JSON. Forbidden: shell
//! evaluation, writes or new policy. Tests: actual generated pretool callbacks.
use crate::{callback_replay::CallbackReplay, pretool_scope::QueryScope};
use serde_json::Value;
use std::{
    env,
    ffi::OsString,
    io::{self, Read},
    path::Path,
};

pub(crate) struct PretoolProcess;

impl PretoolProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 1 {
            crate::exec_python(launcher, args);
        }
        let mut raw = Vec::new();
        if io::stdin().read_to_end(&mut raw).is_err() {
            return CallbackReplay::python(launcher, args, &raw);
        }
        if Self::plain(launcher, args, &raw) {
            0
        } else {
            CallbackReplay::python(launcher, args, &raw)
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
        let Some(scope) = QueryScope::parse(command, Path::new(cwd)) else {
            return false;
        };
        let command = scope.command;
        let cwd = scope.cwd.as_path();
        let Some(executable) = crate::pretool_query::executable(command) else {
            return false;
        };
        let codex = args[0] == "codex-pretool-gate"
            || env::var("MORU_PRETOOL_RUNTIME").is_ok_and(|s| {
                crate::statusline::Renderer::strip(&s).eq_ignore_ascii_case("codex")
            });
        let file_command = (!matches!(executable, "git" | "pwd")).then_some(command);
        if executable == "git" && !unshadowed(cwd, "git") {
            return false;
        }
        if scope
            .output
            .is_some_and(|program| !unshadowed(cwd, program))
        {
            return false;
        }
        if file_command.is_some()
            && !crate::pretool_files::FileQuery::command(command)
                .is_some_and(|query| query.ready(cwd))
        {
            return false;
        }
        crate::pretool_guard::CallbackGuard::root(launcher, executable).is_some()
            && (!codex
                || crate::pretool_transcript::safe(
                    &payload,
                    if scope.absolute_cd {
                        None
                    } else {
                        file_command
                    },
                    if scope.absolute_cd {
                        None
                    } else {
                        scope.output
                    },
                ))
    }
}

fn unshadowed(cwd: &Path, executable: &str) -> bool {
    let Ok(actual) = env::current_dir() else {
        return false;
    };
    [cwd, actual.as_path()].iter().all(|path| {
        std::fs::symlink_metadata(path.join(executable))
            .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
    })
}
