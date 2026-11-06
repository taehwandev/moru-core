//! owner: NextCli; allowed imports: std, PythonText and local CLI rendering;
//! forbidden imports: filesystem/process effects; callers/tests: NextProcess;
//! verification: argparse grammar, precedence and builder-profile parity.
#[path = "next_cli_render.rs"]
mod render;
use crate::python_text::PythonText;
use std::{
    ffi::OsString,
    path::{Path, PathBuf},
};
pub(super) struct NextCli {
    pub project: PathBuf,
    pub evidence: Option<PathBuf>,
    pub format: String,
    pub exit: Option<(i32, String, bool)>,
}
impl NextCli {
    pub(super) fn plain_exit(stderr: bool) -> bool {
        render::CliRender::plain_exit(stderr)
    }
    const OPTIONS: [&'static str; 4] = ["--help", "--project", "--evidence", "--format"];
    const SHORT: &'static str = env!("MORU_ARGPARSE_SHORT_HELP");
    pub(super) fn parse(args: &[OsString], cwd: &Path) -> Option<Self> {
        let mut result = Self {
            project: cwd.into(),
            evidence: None,
            format: "markdown".into(),
            exit: None,
        };
        let args = args
            .iter()
            .map(|a| a.to_str())
            .collect::<Option<Vec<_>>>()?;
        if env!("MORU_ARGPARSE_AMBIGUITY") == "prescan" {
            for arg in args.iter().take_while(|arg| **arg != "--") {
                if let Err(message) = Self::name(arg) {
                    return result.error(&message);
                }
            }
        }
        let mut extras = Vec::new();
        let mut i = 0;
        while i < args.len() {
            let arg = args[i];
            if arg == "--" {
                extras.extend_from_slice(&args[i..]);
                break;
            }
            let (key, explicit) = arg
                .split_once('=')
                .map_or((arg, None), |(k, v)| (k, Some(v)));
            let name = match Self::name(arg) {
                Ok(name) => name,
                Err(message) => return result.error(&message),
            };
            match name {
                Some("--help") => return result.help(arg, key, explicit),
                Some(name) => {
                    let value = if let Some(value) = explicit {
                        value
                    } else {
                        let Some(value) = args.get(i + 1) else {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        };
                        if *value == "--" || Self::option(value) {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        }
                        i += 1;
                        value
                    };
                    match name {
                        "--project" => result.project = PathBuf::from(value),
                        "--evidence" => result.evidence = Some(PathBuf::from(value)),
                        "--format" => {
                            if !matches!(value, "markdown" | "json") {
                                return result.error(&format!("argument --format: invalid choice: {} (choose from 'markdown', 'json')", PythonText::repr(value)));
                            }
                            result.format = value.into();
                        }
                        _ => unreachable!(),
                    }
                }
                None => extras.push(arg),
            }
            i += 1;
        }
        if !extras.is_empty() {
            return result.error(&format!("unrecognized arguments: {}", extras.join(" ")));
        }
        Some(result)
    }

    fn help(mut self, arg: &str, key: &str, explicit: Option<&str>) -> Option<Self> {
        let value = if Self::SHORT == "eager" && !key.starts_with("--") {
            if key[1..].chars().all(|c| c == 'h') {
                explicit
            } else {
                None
            }
        } else if key.starts_with("--") || key == "-h" {
            explicit
        } else {
            Some(&arg[2..])
        };
        if let Some(value) = value {
            if Self::SHORT == "legacy" && key == "-h" && value.is_empty() {
                return None;
            }
            let rest = if Self::SHORT == "eager" || key.starts_with("--") {
                value
            } else {
                value.trim_start_matches('h')
            };
            if Self::SHORT == "eager"
                || key.starts_with("--")
                || !rest.is_empty()
                || value.is_empty()
            {
                return self.error(&format!(
                    "argument -h/--help: ignored explicit argument {}",
                    PythonText::repr(rest)
                ));
            }
        }
        self.exit = Some((
            0,
            render::CliRender::help(render::CliRender::width()?),
            false,
        ));
        Some(self)
    }

    fn error(mut self, message: &str) -> Option<Self> {
        self.exit = Some((
            2,
            format!(
                "{}agent_next_action.py: error: {message}\n",
                render::CliRender::usage(render::CliRender::width()?)
            ),
            true,
        ));
        Some(self)
    }

    fn name(arg: &str) -> Result<Option<&'static str>, String> {
        let key = arg.split_once('=').map_or(arg, |(key, _)| key);
        if key.starts_with("--") {
            let matches: Vec<_> = Self::OPTIONS
                .into_iter()
                .filter(|name| name.starts_with(key))
                .collect();
            if matches.len() > 1 {
                return Err(format!(
                    "ambiguous option: {arg} could match {}",
                    matches.join(", ")
                ));
            }
            Ok(matches.into_iter().next())
        } else {
            Ok(key.starts_with("-h").then_some("--help"))
        }
    }

    fn option(value: &str) -> bool {
        // argparse resolves known options before its space/negative-number exceptions.
        if !matches!(Self::name(value), Ok(None)) {
            return true;
        }
        if !value.starts_with('-') || value == "-" || value.contains(' ') {
            return false;
        }
        let n = value[1..].strip_suffix('\n').unwrap_or(&value[1..]);
        if env!("MORU_ARGPARSE_NEGATIVE_NUMBER") == "prefix" {
            return !n
                .strip_prefix('.')
                .unwrap_or(n)
                .chars()
                .next()
                .is_some_and(PythonText::decimal);
        }
        let numeric = if let Some((a, b)) = n.split_once('.') {
            !b.is_empty()
                && a.chars().all(PythonText::decimal)
                && b.chars().all(PythonText::decimal)
        } else {
            !n.is_empty() && n.chars().all(PythonText::decimal)
        };
        !numeric
    }
}

#[cfg(test)]
#[path = "next_cli_tests.rs"]
mod tests;
