//! Owner: closed literal cd scope and single read-output pipe recognition.
//! Allowed: literal argv helper and std paths. Forbidden: execution, state writes,
//! general shell parsing and authority. Callers/tests: PretoolProcess and actual
//! native query callbacks; verification includes quotes, shadows and fallback.
use std::path::{Path, PathBuf};

pub(crate) struct QueryScope<'a> {
    pub(crate) command: &'a str,
    pub(crate) cwd: PathBuf,
    pub(crate) absolute_cd: bool,
    pub(crate) output: Option<&'static str>,
}

impl<'a> QueryScope<'a> {
    pub(crate) fn parse(command: &'a str, cwd: &Path) -> Option<Self> {
        if command.len() > 16 * 1024 || command.chars().any(|c| c.is_control() && c != '\t') {
            return None;
        }
        let mut result = Self {
            command,
            cwd: cwd.to_owned(),
            absolute_cd: false,
            output: None,
        };
        if let Some(index) = operator(command, b"&&") {
            let words = crate::literal_args::LiteralArgs::parse(&command[..index])?;
            let [cd, directory] = words.as_slice() else {
                return None;
            };
            if cd != "cd" || !Path::new(directory).is_absolute() {
                return None;
            }
            result.cwd = Path::new(directory).canonicalize().ok()?;
            if !result.cwd.is_dir() {
                return None;
            }
            result.absolute_cd = true;
            result.command = &command[index + 2..];
        }
        if let Some(index) = operator(result.command, b"|") {
            let words = crate::literal_args::LiteralArgs::parse(&result.command[index + 1..])?;
            let words: Vec<_> = words.iter().map(String::as_str).collect();
            result.output = Some(match words.as_slice() {
                [program @ ("head" | "tail"), "-n", count]
                    if !count.is_empty()
                        && count.bytes().all(|b| b.is_ascii_digit())
                        && count.parse::<u32>().is_ok_and(|n| n <= 1_000_000) =>
                {
                    if *program == "head" {
                        "head"
                    } else {
                        "tail"
                    }
                }
                ["wc"] | ["wc", "-l" | "-w" | "-c" | "-m"] => "wc",
                _ => return None,
            });
            result.command = &result.command[..index];
        }
        Some(result)
    }
}

// Recognize only an operator outside complete literal quotes. LiteralArgs then
// rejects escapes, concatenation, substitutions and every unsupported shape.
fn operator(command: &str, token: &[u8]) -> Option<usize> {
    let bytes = command.as_bytes();
    let mut quote = None;
    for (index, byte) in bytes.iter().copied().enumerate() {
        if let Some(active) = quote {
            if byte == active {
                quote = None
            }
        } else if matches!(byte, b'\'' | b'"') {
            quote = Some(byte);
        } else if bytes.get(index..index + token.len()) == Some(token) {
            return Some(index);
        }
    }
    None
}
