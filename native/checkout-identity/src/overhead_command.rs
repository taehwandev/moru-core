//! owner: OverheadCommand; allowed imports: source guard, CLI/report/formatter and explicit output;
//! forbidden imports: providers, state mutation; callers/tests: launcher, native overhead CLI;
//! verification: portable output, ordered file writes and no replay after an output attempt.
use crate::{
    overhead_cli::OverheadCli, overhead_clock::OverheadClock, overhead_report::OverheadReport,
    overhead_report_text::OverheadReportText, pretool_guard::CallbackGuard,
    python_text::PythonText,
};
use std::{
    ffi::OsString,
    fs,
    io::{self, ErrorKind, Write},
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
        let Some(clock) = OverheadClock::for_report(
            parsed.since.as_deref(),
            parsed.until.as_deref(),
            parsed.days,
        ) else {
            crate::exec_python(launcher, args);
        };
        let Some(clock) = clock else {
            eprintln!("--since/--until must be ISO timestamps");
            return 1;
        };
        let Some(report) = OverheadReport::build(&parsed, &clock) else {
            crate::exec_python(launcher, args);
        };
        let Some(mut output) = OverheadReportText::json_value(&report) else {
            crate::exec_python(launcher, args);
        };
        output.push('\n');
        let markdown = parsed.md.as_deref().filter(|path| !path.is_empty());
        let markdown = if let Some(path) = markdown {
            let Some(text) = OverheadReportText::markdown_value(&report) else {
                crate::exec_python(launcher, args);
            };
            Some((path, text))
        } else {
            None
        };
        // The old writer truncates and writes JSON first. A later Markdown
        // failure keeps that output and must never cause the command to replay.
        let written = match parsed.out.as_deref().filter(|path| !path.is_empty()) {
            Some(path) => Self::write_file(path, &output),
            None => io::stdout().write_all(output.as_bytes()).is_ok(),
        };
        if !written {
            return 1;
        }
        match markdown {
            Some((path, text)) if !Self::write_file(path, &text) => 1,
            _ => 0,
        }
    }
    fn write_file(path: &str, text: &str) -> bool {
        // Match pathlib on Unix, including literal tildes, preserved "..", a
        // leading double slash and removal of trailing slashes and ".".
        let prefix = if path.starts_with("//") && !path.starts_with("///") {
            "//"
        } else if path.starts_with('/') {
            "/"
        } else {
            ""
        };
        let parts: Vec<_> = path
            .split('/')
            .filter(|part| !part.is_empty() && *part != ".")
            .collect();
        let path = if prefix.is_empty() && parts.is_empty() {
            ".".to_owned()
        } else {
            format!("{prefix}{}", parts.join("/"))
        };
        match fs::write(&path, text) {
            Ok(()) => true,
            Err(error) => {
                let name = match error.kind() {
                    ErrorKind::NotFound => "FileNotFoundError",
                    ErrorKind::PermissionDenied => "PermissionError",
                    ErrorKind::IsADirectory => "IsADirectoryError",
                    ErrorKind::NotADirectory => "NotADirectoryError",
                    _ => "OSError",
                };
                eprintln!("{name}: {error}: {}", PythonText::repr(&path));
                false
            }
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
