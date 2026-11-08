//! owner: OverheadCli; allowed imports: std, PythonText and the pure help formatter;
//! forbidden imports: file/provider/state I/O; callers/tests: native report command;
//! verification: argparse defaults, abbreviations, ordering and integer coercion parity.
#[path = "overhead_cli_help.rs"]
mod help;
use crate::python_text::PythonText;
use help::OverheadCliHelp;
use std::{ffi::OsString, path::Path};

pub(crate) struct OverheadCli {
    pub(crate) days: i64,
    pub(crate) since: Option<String>,
    pub(crate) until: Option<String>,
    pub(crate) projects_dir: String,
    pub(crate) timings: String,
    pub(crate) moru_root: String,
    pub(crate) alias_root: Vec<String>,
    pub(crate) exclude_session: Vec<String>,
    pub(crate) include_subagents: bool,
    pub(crate) min_turns: i64,
    pub(crate) out: Option<String>,
    pub(crate) md: Option<String>,
    pub(crate) exit: Option<i32>,
}
impl OverheadCli {
    const OPTIONS: [&'static str; 13] = [
        "--help",
        "--days",
        "--since",
        "--until",
        "--projects-dir",
        "--timings",
        "--moru-root",
        "--alias-root",
        "--exclude-session",
        "--include-subagents",
        "--min-turns",
        "--out",
        "--md",
    ];
    const SHORT_HELP: &'static str = env!("MORU_ARGPARSE_SHORT_HELP");
    const NEGATIVE: &'static str = env!("MORU_ARGPARSE_NEGATIVE_NUMBER");
    pub(crate) fn parse(root: &Path, home: &Path, args: &[OsString]) -> Option<Self> {
        let mut result = Self {
            days: 30,
            since: None,
            until: None,
            projects_dir: home.join(".claude/projects").to_str()?.into(),
            timings: home.join(".moru/timings.jsonl").to_str()?.into(),
            moru_root: root.to_str()?.into(),
            alias_root: Vec::new(),
            exclude_session: Vec::new(),
            include_subagents: false,
            min_turns: 1,
            out: None,
            md: None,
            exit: None,
        };
        let args = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()?;
        if env!("MORU_ARGPARSE_AMBIGUITY") == "prescan" {
            for arg in args.iter().take_while(|arg| **arg != "--") {
                if let Err(message) = Self::name(arg) {
                    return result.error(&message);
                }
            }
        }
        let mut extras = Vec::new();
        let mut index = 0;
        while index < args.len() {
            let arg = args[index];
            if arg == "--" {
                extras.extend_from_slice(&args[index..]);
                break;
            }
            let (key, explicit) = arg
                .split_once('=')
                .map_or((arg, None), |(key, value)| (key, Some(value)));
            let name = match Self::name(arg) {
                Ok(name) => name,
                Err(message) => return result.error(&message),
            };
            match name {
                Some("--help") => {
                    if let Err(message) = Self::help_argument(arg, key, explicit)? {
                        return result.error(&message);
                    }
                    print!("{}", OverheadCliHelp::help(OverheadCliHelp::width()?));
                    result.exit = Some(0);
                    return Some(result);
                }
                Some("--include-subagents") => {
                    if let Some(value) = explicit {
                        return result.error(&format!(
                            "argument --include-subagents: ignored explicit argument {}",
                            PythonText::repr(value)
                        ));
                    }
                    result.include_subagents = true;
                }
                Some(name) => {
                    let value = if let Some(value) = explicit {
                        value
                    } else {
                        let Some(value) = args.get(index + 1) else {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        };
                        if *value == "--" || Self::option(value) {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        }
                        index += 1;
                        value
                    };
                    if let Err(message) = result.assign(name, value)? {
                        return result.error(&message);
                    }
                }
                None => extras.push(arg),
            }
            index += 1;
        }
        if !extras.is_empty() {
            return result.error(&format!("unrecognized arguments: {}", extras.join(" ")));
        }
        Some(result)
    }
    fn assign(&mut self, name: &str, value: &str) -> Option<Result<(), String>> {
        match name {
            "--days" | "--min-turns" => {
                let number = match Self::integer(value)? {
                    Ok(number) => number,
                    Err(()) => {
                        return Some(Err(format!(
                            "argument {name}: invalid int value: {}",
                            PythonText::repr(value)
                        )))
                    }
                };
                if name == "--days" {
                    self.days = number;
                } else {
                    self.min_turns = number;
                }
            }
            "--since" => self.since = Some(value.into()),
            "--until" => self.until = Some(value.into()),
            "--projects-dir" => self.projects_dir = value.into(),
            "--timings" => self.timings = value.into(),
            "--moru-root" => self.moru_root = value.into(),
            "--alias-root" => self.alias_root.push(value.into()),
            "--exclude-session" => self.exclude_session.push(value.into()),
            "--out" => self.out = Some(value.into()),
            "--md" => self.md = Some(value.into()),
            _ => return None,
        }
        Some(Ok(()))
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
    fn help_argument(arg: &str, key: &str, explicit: Option<&str>) -> Option<Result<(), String>> {
        let value = if Self::SHORT_HELP == "eager" && !key.starts_with("--") {
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
            if Self::SHORT_HELP == "legacy" && key == "-h" && value.is_empty() {
                return None;
            }
            let rest = if Self::SHORT_HELP == "eager" || key.starts_with("--") {
                value
            } else {
                value.trim_start_matches('h')
            };
            if Self::SHORT_HELP == "eager"
                || key.starts_with("--")
                || !rest.is_empty()
                || value.is_empty()
            {
                return Some(Err(format!(
                    "argument -h/--help: ignored explicit argument {}",
                    PythonText::repr(rest)
                )));
            }
        }
        Some(Ok(()))
    }
    fn option(value: &str) -> bool {
        if !value.starts_with('-') || value == "-" || value.contains(' ') {
            return false;
        }
        let number = value[1..].strip_suffix('\n').unwrap_or(&value[1..]);
        if Self::NEGATIVE == "prefix" {
            return !number
                .strip_prefix('.')
                .unwrap_or(number)
                .chars()
                .next()
                .is_some_and(PythonText::decimal);
        }
        let numeric = if let Some((a, b)) = number.split_once('.') {
            !b.is_empty()
                && a.chars().all(PythonText::decimal)
                && b.chars().all(PythonText::decimal)
        } else {
            !number.is_empty() && number.chars().all(PythonText::decimal)
        };
        !numeric
    }
    fn integer(value: &str) -> Option<Result<i64, ()>> {
        let mut normalized = String::new();
        for character in value.chars() {
            if character.is_ascii() {
                normalized.push(character);
            } else if let Some(digit) = PythonText::decimal_value(character) {
                normalized.push(char::from(b'0' + digit));
            } else if PythonText::whitespace(character) {
                normalized.push(' ');
            } else {
                return Some(Err(()));
            }
        }
        let value = normalized.trim_matches([' ', '\t', '\n', '\r', '\x0b', '\x0c']);
        let digits = value.strip_prefix(['+', '-']).unwrap_or(value).as_bytes();
        if digits.is_empty() {
            return Some(Err(()));
        }
        let mut count = 0usize;
        for (index, byte) in digits.iter().enumerate() {
            if byte.is_ascii_digit() {
                count += 1;
            } else if *byte != b'_'
                || index == 0
                || !digits[index - 1].is_ascii_digit()
                || !digits.get(index + 1).is_some_and(u8::is_ascii_digit)
            {
                return Some(Err(()));
            }
        }
        let limit: usize = env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().ok()?;
        if limit > 0 && count > limit {
            return Some(Err(()));
        }
        value.replace('_', "").parse::<i64>().ok().map(Ok)
    }
    fn error(mut self, message: &str) -> Option<Self> {
        eprint!(
            "{}moru_overhead_report.py: error: {message}\n",
            OverheadCliHelp::usage(OverheadCliHelp::width()?)
        );
        self.exit = Some(2);
        Some(self)
    }
}
#[cfg(test)]
#[path = "overhead_cli_tests.rs"]
mod tests;
