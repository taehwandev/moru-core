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
    pub(crate) fn command(command: &'a str) -> Option<Self> {
        let tokens = literal_words(command)?;
        Self::parse(&tokens)
    }

    fn parse(tokens: &[&'a str]) -> Option<Self> {
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
            ["head" | "tail", "-n", count, _, ..]
                if !count.is_empty()
                    && count.bytes().all(|c| c.is_ascii_digit())
                    && count.parse::<u32>().is_ok_and(|n| n <= 1_000_000) =>
            {
                3
            }
            ["head" | "tail", _, ..] => 1,
            ["wc", "-l" | "-w" | "-c" | "-m", _, ..] => 2,
            ["wc", _, ..] => 1,
            ["sed", "-n", script, _, ..] if print_range(script) => 3,
            ["ls", "-l" | "-a" | "-la" | "-al" | "-lh" | "-lah" | "-alh", ..] => 2,
            ["ls", ..] => 1,
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
            .chars()
            .all(|c| c.is_alphanumeric() || "_./- ".contains(c))
        && !Path::new(word)
            .components()
            .any(|c| c == Component::ParentDir)
}

fn literal_words(command: &str) -> Option<Vec<&str>> {
    if command.len() > 16 * 1024 || command.chars().any(|c| c.is_control() && c != '\t') {
        return None;
    }
    let mut rest = command.trim_matches([' ', '\t']);
    let mut words = Vec::new();
    while !rest.is_empty() {
        let (word, tail) = if rest.starts_with(['\'', '"']) {
            // Whole literal words only: no concatenation, escapes or expansion.
            let end = rest[1..].find(rest.as_bytes()[0] as char)? + 1;
            let word = &rest[1..end];
            let print_script = words.as_slice() == ["sed", "-n"] && print_range(word);
            if words.is_empty() || !(literal_path(word) || print_script) {
                return None;
            }
            (word, &rest[end + 1..])
        } else {
            let end = rest.find([' ', '\t']).unwrap_or(rest.len());
            (&rest[..end], &rest[end..])
        };
        if !tail.is_empty() && !tail.starts_with([' ', '\t']) {
            return None;
        }
        words.push(word);
        if words.len() > 20 {
            return None;
        }
        rest = tail.trim_start_matches([' ', '\t']);
    }
    Some(words)
}

fn print_range(script: &str) -> bool {
    let Some(address) = script.strip_suffix('p') else {
        return false;
    };
    let number = |word: &str| {
        (!word.is_empty() && word.bytes().all(|c| c.is_ascii_digit()))
            .then(|| word.parse::<u32>().ok())
            .flatten()
            .filter(|n| (1..=1_000_000).contains(n))
    };
    match address.split_once(',') {
        Some((first, last)) => {
            matches!((number(first), number(last)), (Some(a), Some(b)) if a <= b)
        }
        None => number(address).is_some(),
    }
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
