//! owner: OverheadCommand; allowed imports: source guard, CLI/report/formatter and stdout;
//! forbidden imports: providers, state mutation, output-file writes; callers/tests: launcher;
//! verification: native report CLI, whole-command write fallback and portable stdout.
use crate::{
    overhead_cli::OverheadCli, overhead_report::OverheadReport,
    overhead_report_text::OverheadReportText, pretool_guard::CallbackGuard,
};
use std::{
    ffi::OsString,
    io::Write,
    path::{Path, PathBuf},
};
pub(crate) struct OverheadCommand;
impl OverheadCommand {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(root) = CallbackGuard::root(launcher, "overhead-report") else {
            crate::exec_python(launcher, args);
        };
        let Some(home) = std::env::var_os("HOME").map(PathBuf::from) else {
            crate::exec_python(launcher, args);
        };
        if home.to_str().is_none_or(|s| s.starts_with("//")) {
            crate::exec_python(launcher, args);
        }
        let home = home.components().collect::<PathBuf>();
        let root = Self::default_root(&root);
        let Some(parsed) = OverheadCli::parse(&root, &home, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        if let Some(code) = parsed.exit {
            return code;
        }
        // Output files retain the original writer's ordered partial-failure and
        // exception contract. Never start that phase and replay it in Python.
        if parsed.out.as_ref().is_some_and(|s| !s.is_empty())
            || parsed.md.as_ref().is_some_and(|s| !s.is_empty())
        {
            crate::exec_python(launcher, args);
        }
        let Some(report) = OverheadReport::build(&parsed) else {
            crate::exec_python(launcher, args);
        };
        let Some(mut output) = OverheadReportText::json(&report) else {
            crate::exec_python(launcher, args);
        };
        output.push('\n');
        if std::io::stdout().write_all(output.as_bytes()).is_ok() {
            0
        } else {
            1
        }
    }
    fn default_root(root: &Path) -> PathBuf {
        let Some(parent) = root.parent() else {
            return root.to_owned();
        };
        if let Some(name) = parent
            .file_name()
            .and_then(|s| s.to_str())
            .and_then(|s| s.strip_suffix("-worktrees"))
        {
            parent.with_file_name(name)
        } else {
            root.to_owned()
        }
    }
}
