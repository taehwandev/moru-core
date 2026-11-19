//! owner: offline evaluator public argv admission; allowed imports: std paths
//! and argument strings; forbidden imports: file reads, subprocesses, runtime
//! options; callers/tests: BehaviorEvalCli and public CLI differential tests.

use std::{
    ffi::OsString,
    path::{Path, PathBuf},
};

pub(super) struct BehaviorEvalPublicArgs;

impl BehaviorEvalPublicArgs {
    const OPTIONS: [&str; 4] = ["--cases", "--traces", "--artifact-root", "--providers"];
    const REQUIRED: usize = 3;

    pub(super) fn normalize(args: &[OsString]) -> Result<Option<Vec<OsString>>, String> {
        let Some(args) = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()
        else {
            return Ok(None);
        };
        let mut words = args.into_iter().peekable();
        let mut normalized = Vec::new();
        let mut seen = [false; Self::REQUIRED];
        let value = |word: &&str| !word.starts_with('-');
        while let Some(word) = words.next() {
            let (option, inline) = word
                .split_once('=')
                .map_or((word, None), |(key, text)| (key, Some(text)));
            let Some(index) = Self::option_index(option) else {
                return Ok(None);
            };
            let name = Self::OPTIONS[index];
            let argument = if let Some(text) = inline {
                text.to_owned()
            } else {
                let Some(first) = words.next_if(value) else {
                    if words.peek().is_some_and(|word| {
                        Self::option_index(word.split('=').next().unwrap_or(word)).is_none()
                    }) {
                        // A dash-prefixed value or help can change argparse precedence.
                        return Ok(None);
                    }
                    let count = if name == "--providers" {
                        "at least one"
                    } else {
                        "one"
                    };
                    return Err(format!("argument {name}: expected {count} argument"));
                };
                if name == "--providers" {
                    let mut values = vec![first];
                    while let Some(text) = words.next_if(value) {
                        values.push(text);
                    }
                    values.join(",")
                } else {
                    first.to_owned()
                }
            };
            let argument = if name == "--artifact-root" {
                // Match pathlib's lexical normalization before symlink checks.
                // POSIX paths starting with two slashes retain Python handling.
                if argument.is_empty() || argument.starts_with("//") {
                    return Ok(None);
                }
                let Ok(path) = Path::new(&argument)
                    .components()
                    .collect::<PathBuf>()
                    .into_os_string()
                    .into_string()
                else {
                    return Ok(None);
                };
                path
            } else {
                argument
            };
            normalized.push(OsString::from(format!("{name}={argument}")));
            if let Some(slot) = seen.get_mut(index) {
                *slot = true;
            }
        }
        let missing: Vec<_> = seen
            .into_iter()
            .zip(Self::OPTIONS)
            .filter_map(|(present, name)| (!present).then_some(name))
            .collect();
        if missing.is_empty() {
            Ok(Some(normalized))
        } else {
            Err(format!(
                "the following arguments are required: {}",
                missing.join(", ")
            ))
        }
    }

    fn option_index(option: &str) -> Option<usize> {
        if !option.starts_with("--") || option.len() <= 2 {
            return None;
        }
        let mut matches = Self::OPTIONS
            .iter()
            .enumerate()
            .filter(|(_, name)| name.starts_with(option));
        let (index, _) = matches.next()?;
        matches.next().is_none().then_some(index)
    }
}
