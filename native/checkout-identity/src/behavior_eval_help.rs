//! owner: offline evaluator help profile; allowed imports: pure argparse help
//! layout and stdout; forbidden imports: evidence, runtime state and processes.
//! callers/tests: BehaviorEvalCli and original Python help oracle.

use crate::argparse_help::ArgparseHelp;
use std::{
    ffi::OsString,
    io::{self, Write},
};

pub(super) struct BehaviorEvalHelp;

impl BehaviorEvalHelp {
    pub(super) fn run(args: &[OsString]) -> Option<i32> {
        let [profile, marker, help] = args else {
            return None;
        };
        if marker != "--public-args"
            || !matches!(help.to_str()?, "-h" | "--h" | "--he" | "--hel" | "--help")
        {
            return None;
        }
        let (layout, width) = profile
            .to_str()?
            .strip_prefix("--help-layout=")?
            .split_once(',')?;
        let title = match layout {
            "legacy" => "optional arguments:",
            "modern" | "grouped" => "options:",
            _ => return None,
        };
        let width = width.parse::<usize>().ok()?;
        if !(32..=512).contains(&width) {
            return None;
        }
        // Older argparse wraps required flags and metavariables separately.
        let parts: &[&str] = if layout == "grouped" {
            &[
                "[-h]",
                "--cases CASES",
                "--traces TRACES",
                "--artifact-root ARTIFACT_ROOT",
                "[--providers PROVIDERS [PROVIDERS ...]]",
            ]
        } else {
            &[
                "[-h]",
                "--cases",
                "CASES",
                "--traces",
                "TRACES",
                "--artifact-root",
                "ARTIFACT_ROOT",
                "[--providers PROVIDERS [PROVIDERS ...]]",
            ]
        };
        let rows = [
            ("-h, --help", "show this help message and exit"),
            ("--cases CASES", "Cases JSON"),
            ("--traces TRACES", "Traces JSON"),
            (
                "--artifact-root ARTIFACT_ROOT",
                "Root holding <provider>/<case_id>/ artifacts",
            ),
            (
                "--providers PROVIDERS [PROVIDERS ...]",
                "Optional provider subset.",
            ),
        ];
        let text = ArgparseHelp::help(
            "agent_behavior_eval.py",
            parts,
            "Offline agent behavior grader (supplied evidence only, not live scores).",
            title,
            &rows,
            width,
        );
        Some(i32::from(
            io::stdout().lock().write_all(text.as_bytes()).is_err(),
        ))
    }
}
