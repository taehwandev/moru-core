//! owner: ReactManifestCli; allowed imports: std, libc, PythonText; forbidden imports: process/network;
//! callers/tests: ReactManifest and subject tests; verification: argparse CLI parity.
use crate::python_text::PythonText;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
pub struct ReactManifestCli {
    pub manifest: PathBuf,
    pub source: Option<PathBuf>,
    pub remote: bool,
    pub exit: Option<i32>,
}
impl ReactManifestCli {
    const PROG: &'static str = "check_react_rn_external_skill_manifest.py";
    const OPTIONS: [&'static str; 4] = ["--help", "--manifest", "--source-root", "--remote-check"];
    const SHORT_HELP: &'static str = env!("MORU_ARGPARSE_SHORT_HELP");
    const NEGATIVE: &'static str = env!("MORU_ARGPARSE_NEGATIVE_NUMBER");
    const AMBIGUITY: &'static str = env!("MORU_ARGPARSE_AMBIGUITY");
    pub fn parse(root: &Path, args: &[OsString]) -> Option<Self> {
        let mut result=Self { manifest:root.join("common/skills/react-rn-external-skill-source-coverage/references/source-manifest.json"), source:None,remote:false,exit:None };
        let args = args
            .iter()
            .map(|a| a.to_str())
            .collect::<Option<Vec<_>>>()?;
        let mut extras = Vec::new();
        // argparse classifies every option before executing help or consuming values.
        for arg in args
            .iter()
            .take(if Self::AMBIGUITY == "prescan" {
                args.len()
            } else {
                0
            })
            .take_while(|arg| **arg != "--")
        {
            if let Err(message) = Self::name(arg) {
                return result.error(&message);
            }
        }
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
                Some("--help") => {
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
                    if let Some(v) = value {
                        // Python 3.9 short-option clustering raises IndexError for -h=.
                        if Self::SHORT_HELP == "legacy" && key == "-h" && v.is_empty() {
                            return None;
                        }
                        let rest = if Self::SHORT_HELP == "eager" || key.starts_with("--") {
                            v
                        } else {
                            v.trim_start_matches('h')
                        };
                        if Self::SHORT_HELP == "eager"
                            || key.starts_with("--")
                            || !rest.is_empty()
                            || v.is_empty()
                        {
                            return result.error(&format!(
                                "argument -h/--help: ignored explicit argument {}",
                                PythonText::repr(rest)
                            ));
                        }
                    }
                    print!("{}", Self::help(Self::width()?)?);
                    result.exit = Some(0);
                    return Some(result);
                }
                Some("--remote-check") => {
                    if let Some(v) = explicit {
                        return result.error(&format!(
                            "argument --remote-check: ignored explicit argument {}",
                            PythonText::repr(v)
                        ));
                    }
                    result.remote = true;
                }
                Some(name) => {
                    let value = if let Some(v) = explicit {
                        v
                    } else {
                        let Some(v) = args.get(i + 1) else {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        };
                        if *v == "--" || Self::option(v)? {
                            return result
                                .error(&format!("argument {name}: expected one argument"));
                        }
                        i += 1;
                        v
                    };
                    if name == "--manifest" {
                        result.manifest = PathBuf::from(value);
                    } else {
                        result.source = Some(PathBuf::from(value));
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
    fn error(mut self, message: &str) -> Option<Self> {
        eprint!(
            "{}{}: error: {message}\n",
            Self::usage(Self::width()?),
            Self::PROG
        );
        self.exit = Some(2);
        Some(self)
    }
    fn option(value: &str) -> Option<bool> {
        if !value.starts_with('-') || value == "-" || value.contains(' ') {
            return Some(false);
        }
        let n = value[1..].strip_suffix('\n').unwrap_or(&value[1..]);
        if Self::NEGATIVE == "prefix" {
            return Some(
                !n.strip_prefix('.')
                    .unwrap_or(n)
                    .chars()
                    .next()
                    .is_some_and(PythonText::decimal),
            );
        }
        let numeric = if let Some((a, b)) = n.split_once('.') {
            !b.is_empty()
                && a.chars().all(PythonText::decimal)
                && b.chars().all(PythonText::decimal)
        } else {
            !n.is_empty() && n.chars().all(PythonText::decimal)
        };
        Some(!numeric)
    }
    fn width() -> Option<usize> {
        let env = std::env::var("COLUMNS").ok();
        if env
            .as_ref()
            .is_some_and(|v| !v.is_ascii() || v.contains('_'))
        {
            return None;
        }
        let columns = env
            .and_then(|v| v.trim().parse::<i64>().ok())
            .filter(|n| *n > 0)
            .unwrap_or_else(|| {
                #[cfg(unix)]
                {
                    let mut size: libc::winsize = unsafe { std::mem::zeroed() };
                    if unsafe { libc::ioctl(1, libc::TIOCGWINSZ, &mut size) } == 0
                        && size.ws_col > 0
                    {
                        return i64::from(size.ws_col);
                    }
                }
                80
            });
        (columns > 2 && columns <= 10000).then_some(columns as usize - 2)
    }
    fn usage(width: usize) -> String {
        let parts = [
            "[-h]",
            "[--manifest MANIFEST]",
            "[--source-root SOURCE_ROOT]",
            "[--remote-check]",
        ];
        let one = format!("usage: {} {}", Self::PROG, parts.join(" "));
        if one.len() <= width {
            return format!("{one}\n");
        }
        let mut out = format!("usage: {}", Self::PROG);
        let short = (7 + Self::PROG.len()) as f64 <= 0.75 * width as f64;
        let indent = if short { 8 + Self::PROG.len() } else { 7 };
        let mut length = out.len();
        let mut has_part = short;
        if !short {
            out.push('\n');
            out.push_str(&" ".repeat(indent));
            length = indent;
        }
        for part in parts {
            if has_part && length + 1 + part.len() > width {
                out.push('\n');
                out.push_str(&" ".repeat(indent));
                length = indent;
                has_part = false;
            }
            if has_part {
                out.push(' ');
                length += 1;
            }
            out.push_str(part);
            length += part.len();
            has_part = true;
        }
        out.push('\n');
        out
    }
    fn wrap(text: &str, width: usize) -> Vec<String> {
        let mut lines = Vec::new();
        let mut line = String::new();
        for word in text.split_whitespace() {
            let mut word = word;
            if !line.is_empty() && line.len() + 1 + word.len() > width {
                if word.len() > width && line.len() + 1 < width {
                    let take = width - line.len() - 1;
                    line.push(' ');
                    line.push_str(&word[..take]);
                    word = &word[take..];
                }
                lines.push(std::mem::take(&mut line));
            }
            while word.len() > width {
                lines.push(word[..width].into());
                word = &word[width..];
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        if !line.is_empty() {
            lines.push(line);
        }
        lines
    }
    fn help(width: usize) -> Option<String> {
        let mut out = Self::usage(width);
        out.push('\n');
        out.push_str(
            &Self::wrap(
                "Validate the reviewed React/RN external skill source manifest.",
                width,
            )
            .join("\n"),
        );
        // Bound to the artifact's build-time argparse version, never queried at runtime.
        out.push_str("\n\n");
        out.push_str(option_env!("MORU_ARGPARSE_OPTIONS_TITLE").unwrap_or("optional arguments:"));
        out.push('\n');
        let pos = 24.min(width.saturating_sub(20).max(4));
        let help_width = width.saturating_sub(pos).max(11);
        for (name,help) in [("-h, --help","show this help message and exit"),("--manifest MANIFEST",""),("--source-root SOURCE_ROOT",""),("--remote-check","compare each pinned commit with the provider's current remote HEAD; requires network access and is never run by the default offline check")] {
            out.push_str("  ");out.push_str(name);
            if help.is_empty(){out.push('\n');continue;}
            let separate=name.len()>pos.saturating_sub(4);
            if separate{out.push('\n');out.push_str(&" ".repeat(pos));}else{out.push_str(&" ".repeat(pos-2-name.len()));}
            for (i,line) in Self::wrap(help,help_width).iter().enumerate(){if i>0{out.push_str(&" ".repeat(pos));}out.push_str(line);out.push('\n');}
        }
        Some(out)
    }
}
#[cfg(test)]
#[path = "react_manifest_cli_tests.rs"]
mod tests;
