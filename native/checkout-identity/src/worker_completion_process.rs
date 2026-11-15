//! owner: bounded completion protocol; allowed imports: std IO, WorkerCompletion;
//! forbidden: files, scheduling and providers; callers/tests: launcher_main,
//! worker_completion_contract; verification: actual native stdin/stdout.
use crate::worker_completion::WorkerCompletion;
use std::ffi::OsString;
use std::io::{self, Read};

pub(crate) struct WorkerCompletionProcess;

impl WorkerCompletionProcess {
    pub(crate) fn dispatch(args: &[OsString]) {
        if !args
            .first()
            .is_some_and(|a| a == "--worker-completion-probe")
        {
            return;
        }
        let mut raw = Vec::new();
        let valid = args.len() == 1
            && io::stdin().take(16385).read_to_end(&mut raw).is_ok()
            && raw.len() <= 16384;
        let result = valid.then(|| serde_json::from_slice(&raw).ok()).flatten();
        match result {
            Some(input) => println!("{}", WorkerCompletion::accepts(&input)),
            None => std::process::exit(2),
        }
        std::process::exit(0);
    }
}
