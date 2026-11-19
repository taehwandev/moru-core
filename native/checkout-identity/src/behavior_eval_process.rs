//! owner: user-facing behavior-eval launcher route; allowed imports: native
//! grader, source and encoding checks, exact Python fallback. Forbidden:
//! provider calls and evaluation policy. Callers/tests: launcher and CLI parity.

use crate::{
    behavior_eval_cli::BehaviorEvalCli, pretool_guard::CallbackGuard,
    python_encoding::PythonEncoding,
};
use std::ffi::OsString;

pub(crate) struct BehaviorEvalProcess;

impl BehaviorEvalProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if CallbackGuard::root(launcher, "behavior-eval").is_none() || !PythonEncoding::utf8() {
            crate::exec_python(launcher, args);
        }
        // Use the lowest supported caller limit without starting an interpreter.
        // A larger integer, syntax profile, or customized environment is replayed
        // through the original parser instead of assuming the builder's choices.
        let native: Vec<_> = [
            "--stable-errors-only",
            "--int-max-str-digits=640",
            "--public-args",
        ]
        .into_iter()
        .map(OsString::from)
        .chain(args[1..].iter().cloned())
        .collect();
        match BehaviorEvalCli::run(&native) {
            78 => crate::exec_python(launcher, args),
            code => code,
        }
    }
}
