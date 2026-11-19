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

    pub(super) fn normalize(args: &[OsString]) -> Option<Vec<OsString>> {
        let args = args
            .iter()
            .map(|arg| arg.to_str())
            .collect::<Option<Vec<_>>>()?;
        let mut words = args.into_iter().peekable();
        let mut normalized = Vec::new();
        let value = |word: &&str| !word.starts_with('-');
        while let Some(word) = words.next() {
            let (option, inline) = word
                .split_once('=')
                .map_or((word, None), |(key, text)| (key, Some(text)));
            if !option.starts_with("--") || option.len() <= 2 {
                return None;
            }
            let mut matches = Self::OPTIONS.iter().filter(|name| name.starts_with(option));
            let name = matches.next()?;
            if matches.next().is_some() {
                return None;
            }
            let argument = if let Some(text) = inline {
                text.to_owned()
            } else if *name == "--providers" {
                let mut values = vec![words.next_if(value)?];
                while let Some(text) = words.next_if(value) {
                    values.push(text);
                }
                values.join(",")
            } else {
                words.next_if(value)?.to_owned()
            };
            let argument = if *name == "--artifact-root" {
                // Match pathlib's lexical normalization before symlink checks.
                // POSIX paths starting with two slashes retain Python handling.
                if argument.is_empty() || argument.starts_with("//") {
                    return None;
                }
                Path::new(&argument)
                    .components()
                    .collect::<PathBuf>()
                    .into_os_string()
                    .into_string()
                    .ok()?
            } else {
                argument
            };
            normalized.push(OsString::from(format!("{name}={argument}")));
        }
        Some(normalized)
    }
}
