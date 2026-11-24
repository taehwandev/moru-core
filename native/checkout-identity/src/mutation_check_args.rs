//! owner: mutation-check public argument parsing and scoped argparse diagnostics.
//! allowed imports: OS argument strings, console profile and the shared usage formatter.
//! forbidden imports: project files, subprocesses and mutation effects.
//! callers/tests: mutation-check launcher and its Python differential fixtures.
//! verification: unique abbreviations, argument precedence and pre-effect output.
use crate::{argparse_help::ArgparseHelp, python_text::PythonText};
use std::{env, ffi::OsString, path::Path};

pub(super) enum Parsed<'a> {
    Run {
        spec: &'a Path,
        selector: &'a str,
        root: &'a Path,
    },
    Help,
    Error(String),
}

const OPTIONS: [&str; 4] = ["--help", "--spec", "--test", "--root"];
const PARTS: [&str; 4] = ["[-h]", "--spec SPEC", "--test TEST", "[--root ROOT]"];
const PROG: &str = "mutation-check.py";

impl<'a> Parsed<'a> {
    pub(super) fn parse(args: &'a [OsString], default_root: &'a Path) -> Option<Self> {
        let mut args = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()?
            .into_iter();
        let (mut spec, mut selector, mut root) = (None, None, default_root);
        let mut extras = Vec::new();
        while let Some(token) = args.next() {
            if token == "--" {
                extras.push(token);
                extras.extend(args);
                break;
            }
            // Grouped short options and their diagnostics vary across argparse versions.
            if token.starts_with("-h") && !matches!(token, "-h") {
                return None;
            }
            let (key, explicit) = token
                .split_once('=')
                .map_or((token, None), |(key, value)| (key, Some(value)));
            let option = if key == "-h" {
                Some("--help")
            } else if key.starts_with("--") && key.len() > 2 {
                OPTIONS.into_iter().find(|option| option.starts_with(key))
            } else {
                None
            };
            let Some(option) = option else {
                extras.push(token);
                continue;
            };
            if option == "--help" {
                return Some(match explicit {
                    Some(value) => Self::Error(format!(
                        "argument -h/--help: ignored explicit argument {}",
                        PythonText::repr(value)
                    )),
                    None => Self::Help,
                });
            }
            let value = if let Some(value) = explicit {
                value
            } else {
                let Some(value) = args.next() else {
                    return Some(Self::missing_value(option));
                };
                if value.starts_with('-') && value != "-" {
                    if value.contains(' ')
                        || value[1..].starts_with('.')
                        || value[1..].chars().next().is_some_and(PythonText::decimal)
                    {
                        return None;
                    }
                    return Some(Self::missing_value(option));
                }
                value
            };
            match option {
                "--spec" => spec = Some(Path::new(if value.is_empty() { "." } else { value })),
                "--test" => selector = Some(value),
                "--root" => root = Path::new(if value.is_empty() { "." } else { value }),
                _ => return None,
            }
        }
        let missing = [("--spec", spec.is_none()), ("--test", selector.is_none())]
            .into_iter()
            .filter_map(|(name, absent)| absent.then_some(name))
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Some(Self::Error(format!(
                "the following arguments are required: {}",
                missing.join(", ")
            )));
        }
        if !extras.is_empty() {
            return Some(Self::Error(format!(
                "unrecognized arguments: {}",
                extras.join(" ")
            )));
        }
        Some(Self::Run {
            spec: spec?,
            selector: selector?,
            root,
        })
    }

    fn missing_value(option: &str) -> Self {
        Self::Error(format!("argument {option}: expected one argument"))
    }

    pub(super) fn show_help() -> Option<i32> {
        let width = Self::diagnostic_width()?;
        if width < 75 {
            return None;
        }
        print!(
            "{}\nJudge a mutation by the test run's exit code, never by reading its output.\n\n{}\n  -h, --help   show this help message and exit\n  --spec SPEC\n  --test TEST  unittest selector to run\n  --root ROOT\n",
            ArgparseHelp::usage(PROG, &PARTS, width), env!("MORU_ARGPARSE_OPTIONS_TITLE")
        );
        Some(0)
    }

    pub(super) fn show_error(message: String) -> Option<i32> {
        let width = Self::diagnostic_width()?;
        eprint!(
            "{}{PROG}: error: {message}\n",
            ArgparseHelp::usage(PROG, &PARTS, width)
        );
        Some(2)
    }

    fn diagnostic_width() -> Option<usize> {
        if unsafe { libc::isatty(1) == 1 || libc::isatty(2) == 1 }
            || env::var_os("FORCE_COLOR").is_some()
            || env::var_os("LANGUAGE").is_some_and(|value| !value.is_empty())
        {
            return None;
        }
        for key in ["LC_ALL", "LC_MESSAGES", "LANG"] {
            let Some(locale) = env::var_os(key).filter(|value| !value.is_empty()) else {
                continue;
            };
            let language = locale.to_str()?.split(['.', '@']).next()?;
            if !matches!(language, "C" | "POSIX" | "en_US" | "en_GB") {
                return None;
            }
            break;
        }
        match env::var_os("COLUMNS") {
            None => Some(78),
            Some(width) => {
                let columns: usize = width.to_str()?.parse().ok()?;
                (42..=10000)
                    .contains(&columns)
                    .then_some(columns.saturating_sub(2))
            }
        }
    }
}
