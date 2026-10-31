//! Closed file-query shapes and conservative filesystem eligibility.
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

pub(crate) struct FileQuery<'a> {
    tokens: Vec<&'a str>,
    operands: usize,
}

impl<'a> FileQuery<'a> {
    pub(crate) fn parse(tokens: &[&'a str]) -> Option<Self> {
        if tokens.len() > 20 {
            return None;
        }
        let operands = match tokens {
            ["rg", "--files", ..] => 2,
            ["rg", "-n", pattern, ..]
                if !pattern.is_empty()
                    && pattern
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || c == b'_') =>
            {
                3
            }
            ["cat", "-n", _, ..] => 2,
            ["cat", _, ..] => 1,
            ["head", "-n", count, _, ..]
                if !count.is_empty()
                    && count.bytes().all(|c| c.is_ascii_digit())
                    && count.parse::<u32>().is_ok_and(|n| n <= 1_000_000) =>
            {
                3
            }
            ["head", _, ..] => 1,
            _ => return None,
        };
        if !tokens[operands..].iter().all(|word| literal_path(word)) {
            return None;
        }
        Some(Self {
            tokens: tokens.to_vec(),
            operands,
        })
    }

    pub(crate) fn executable(&self) -> &'a str {
        self.tokens[0]
    }

    pub(crate) fn ready(&self, cwd: &Path) -> bool {
        // Python's bare-alias resolution uses its process cwd, which need not
        // match the payload or selected workdir. Keep both contexts conservative.
        let Ok(process_cwd) = std::env::current_dir() else {
            return false;
        };
        let absent = |directory: &Path| {
            fs::symlink_metadata(directory.join(self.tokens[0]))
                .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
        };
        if !absent(cwd) || !absent(&process_cwd) {
            return false;
        }
        self.tokens
            .iter()
            .filter(|p| !p.starts_with('-'))
            .all(|p| resolvable_prefix(&cwd.join(p)))
            && self.tokens[self.operands..]
                .iter()
                .all(|p| cwd.join(p).canonicalize().is_ok())
    }
}

fn literal_path(word: &str) -> bool {
    !word.is_empty()
        && !word.starts_with('-')
        && word
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_./-".contains(&c))
        && !Path::new(word)
            .components()
            .any(|c| c == Component::ParentDir)
}

fn resolvable_prefix(path: &Path) -> bool {
    let mut prefix = PathBuf::new();
    for component in path.components() {
        prefix.push(component);
        match fs::symlink_metadata(&prefix) {
            Ok(_) if prefix.canonicalize().is_ok() => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return true,
            _ => return false,
        }
    }
    true
}
