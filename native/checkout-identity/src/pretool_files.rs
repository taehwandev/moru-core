//! Closed file-query shapes and conservative filesystem eligibility.
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

pub(crate) struct FileQuery {
    tokens: Vec<String>,
    paths: Vec<usize>,
}

impl FileQuery {
    pub(crate) fn command(command: &str) -> Option<Self> {
        let tokens = crate::literal_args::LiteralArgs::parse(command)?;
        Self::parse(tokens)
    }

    pub(crate) fn stdin_filter(command: &str) -> Option<Self> {
        let mut tokens = crate::literal_args::LiteralArgs::parse(command)?;
        if tokens.first().map(String::as_str) != Some("rg")
            || tokens.get(1).map(String::as_str) == Some("--files")
        {
            return None;
        }
        // The extra -n is validation metadata only; no command is executed.
        if tokens.get(1).map(String::as_str) != Some("-n") {
            tokens.insert(1, "-n".to_owned());
        }
        let query = Self::parse(tokens)?;
        query.paths.is_empty().then_some(query)
    }

    fn parse(tokens: Vec<String>) -> Option<Self> {
        if tokens.len() > 20 {
            return None;
        }
        let values: Vec<_> = tokens.iter().map(String::as_str).collect();
        if values.first() == Some(&"rg") {
            let paths = rg_paths(&values)?;
            return Some(Self { tokens, paths });
        }
        let operands = match values.as_slice() {
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
        if !values[operands..].iter().all(|word| literal_path(word)) {
            return None;
        }
        Some(Self {
            paths: (operands..tokens.len()).collect(),
            tokens,
        })
    }

    pub(crate) fn executable(&self) -> &'static str {
        match self.tokens[0].as_str() {
            "rg" => "rg",
            "cat" => "cat",
            "head" => "head",
            "tail" => "tail",
            "wc" => "wc",
            "sed" => "sed",
            "ls" => "ls",
            _ => unreachable!(),
        }
    }

    pub(crate) fn ready(&self, cwd: &Path) -> bool {
        // Python's bare-alias resolution uses its process cwd, which need not
        // match the payload or selected workdir. Keep both contexts conservative.
        let Ok(process_cwd) = std::env::current_dir() else {
            return false;
        };
        let absent = |directory: &Path| {
            fs::symlink_metadata(directory.join(&self.tokens[0]))
                .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
        };
        if !absent(cwd) || !absent(&process_cwd) {
            return false;
        }
        self.tokens
            .iter()
            .filter(|p| !p.starts_with('-'))
            .all(|p| resolvable_prefix(&cwd.join(p)))
            && self
                .paths
                .iter()
                .all(|index| cwd.join(&self.tokens[*index]).canonicalize().is_ok())
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

fn rg_paths(tokens: &[&str]) -> Option<Vec<usize>> {
    let files = match tokens.get(1)? {
        &"--files" => true,
        &"-n" => false,
        _ => return None,
    };
    let (mut index, mut pattern, mut literal) = (2, files, false);
    let mut paths = Vec::new();
    while index < tokens.len() {
        let word = tokens[index];
        if !literal && matches!(word, "-g" | "--glob") {
            index += 1;
            let glob = tokens.get(index)?;
            if glob.is_empty() || glob.starts_with('-') {
                return None;
            }
        } else if !literal && word.starts_with("--glob=") {
            let glob = word.strip_prefix("--glob=")?;
            if glob.is_empty() || glob.starts_with('-') {
                return None;
            }
        } else if !literal
            && !files
            && matches!(
                word,
                "-A" | "-B" | "-C" | "--after-context" | "--before-context" | "--context"
            )
        {
            index += 1;
            if !context_count(tokens.get(index)?) {
                return None;
            }
        } else if !literal
            && !files
            && [
                "-A",
                "-B",
                "-C",
                "--after-context=",
                "--before-context=",
                "--context=",
            ]
            .iter()
            .any(|prefix| word.starts_with(prefix))
        {
            let value = [
                "-A",
                "-B",
                "-C",
                "--after-context=",
                "--before-context=",
                "--context=",
            ]
            .iter()
            .find_map(|prefix| word.strip_prefix(prefix))?;
            if !context_count(value) {
                return None;
            }
        } else if !literal && word == "--" {
            literal = true;
        } else if !pattern {
            if word.is_empty() || word.starts_with('-') {
                return None;
            }
            pattern = true;
        } else {
            if !literal_path(word) {
                return None;
            }
            paths.push(index);
        }
        index += 1;
    }
    pattern.then_some(paths)
}

fn context_count(word: &str) -> bool {
    !word.is_empty()
        && word.bytes().all(|b| b.is_ascii_digit())
        && word.parse::<u32>().is_ok_and(|n| n <= 1_000_000)
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
