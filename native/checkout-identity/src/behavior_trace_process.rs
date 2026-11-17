//! owner: offline trace protocol ingress; allowed imports: std IO, serde_json,
//! BehaviorTrace; forbidden: providers, files, workflow mutations, Python fallback;
//! callers/tests: launcher_main, behavior_trace_contract; verification: real protocol.
use crate::behavior_trace::BehaviorTrace;
use std::ffi::OsString;
use std::io::{self, Read, Write};

pub(crate) struct BehaviorTraceProcess;

impl BehaviorTraceProcess {
    pub(crate) fn dispatch(args: &[OsString]) {
        if args
            .first()
            .is_some_and(|arg| arg == "--behavior-trace-probe")
        {
            std::process::exit(Self::run(args));
        }
    }

    fn run(args: &[OsString]) -> i32 {
        match Self::read(args) {
            Ok(result) => match serde_json::to_writer(io::stdout().lock(), &result) {
                Ok(()) => 0,
                Err(_) => 1,
            },
            Err(code) => {
                let _ = writeln!(io::stderr(), "behavior_trace: {code}");
                2
            }
        }
    }

    fn read(args: &[OsString]) -> Result<serde_json::Value, &'static str> {
        if args.len() != 1 {
            return Err("invalid_arguments");
        }
        let mut raw = Vec::new();
        io::stdin()
            .take(4 * 1024 * 1024 + 1)
            .read_to_end(&mut raw)
            .map_err(|_| "input_unreadable")?;
        if raw.len() > 4 * 1024 * 1024 {
            return Err("input_too_large");
        }
        let input = serde_json::from_slice(&raw).map_err(|_| "invalid_json")?;
        BehaviorTrace::normalize(&input)
    }
}
