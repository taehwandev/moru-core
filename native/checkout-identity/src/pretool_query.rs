//! Closed plain-query grammar. No shell parsing, execution, or policy mutation.
use std::path::Path;

pub(crate) fn executable(command: &str) -> Option<&'static str> {
    if let Some(query) = crate::pretool_files::FileQuery::command(command) {
        return Some(query.executable());
    }
    let parsed = crate::literal_args::LiteralArgs::parse(command)?;
    let tokens: Vec<_> = parsed.iter().map(String::as_str).collect();
    if tokens.as_slice() == ["pwd"] {
        return Some("pwd");
    }
    if tokens.first() != Some(&"git") {
        return None;
    }
    let rest = if tokens.get(1) == Some(&"-C") {
        let path = Path::new(tokens.get(2)?);
        if !path.is_absolute() || !path.canonicalize().ok()?.is_dir() {
            return None;
        }
        &tokens[3..]
    } else {
        &tokens[1..]
    };
    match rest {
        ["diff", args @ ..] if diff_args(args) => Some("git"),
        ["status", "--short" | "--porcelain" | "--porcelain=v1"]
        | ["status", "--short" | "--porcelain" | "--porcelain=v1", "--branch"]
        | ["status", "--branch", "--short" | "--porcelain" | "--porcelain=v1"]
        | ["remote", "-v"]
        | ["rev-parse", "HEAD" | "--show-toplevel"]
        | ["branch", "--show-current"]
        | ["ls-files"]
        | ["ls-files", "--cached" | "--stage"]
        | ["ls-files", "--others", "--exclude-standard"]
        | ["log", "--oneline"]
        | ["show", "--stat" | "--name-only"]
        | ["tag", "--list"]
        | ["tag", "--list", "--sort=-version:refname"] => Some("git"),
        ["log", args @ ..] if log_args(args) => Some("git"),
        ["diff", before, after, "--stat" | "--check" | "--name-only" | "--name-status" | "--numstat"]
            if revision(before) && revision(after) =>
        {
            Some("git")
        }
        ["show", "--stat" | "--name-only", revision]
            if (7..=64).contains(&revision.len())
                && revision.bytes().all(|b| b.is_ascii_hexdigit()) =>
        {
            Some("git")
        }
        _ => None,
    }
}

fn diff_args(args: &[&str]) -> bool {
    let args = args.strip_prefix(&["--cached"]).unwrap_or(args);
    let args = if args.first().is_some_and(|word| {
        matches!(
            *word,
            "--stat" | "--check" | "--name-only" | "--name-status" | "--numstat" | "--exit-code"
        )
    }) {
        &args[1..]
    } else {
        args
    };
    if args.is_empty() {
        return true;
    }
    let Some(paths) = args.strip_prefix(&["--"]) else {
        return false;
    };
    !paths.is_empty()
        && paths.iter().all(|path| {
            !path.is_empty()
                && !path.starts_with('-')
                && path
                    .chars()
                    .all(|c| c.is_alphanumeric() || "_./- ".contains(c))
                && !Path::new(path)
                    .components()
                    .any(|c| c == std::path::Component::ParentDir)
        })
}

fn log_args(args: &[&str]) -> bool {
    let mut format = false;
    let mut count = false;
    for word in args {
        if log_count(word) && !count {
            count = true;
        } else if !format
            && (*word == "--oneline"
                || ["--format=", "--pretty="].iter().any(|prefix| {
                    word.strip_prefix(prefix)
                        .is_some_and(|v| !v.is_empty() && v.len() <= 512)
                }))
        {
            format = true;
        } else {
            return false;
        }
    }
    format
}

fn revision(word: &str) -> bool {
    if word == "HEAD"
        || ((7..=64).contains(&word.len()) && word.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return true;
    }
    ["HEAD~", "HEAD^"].iter().any(|prefix| {
        word.strip_prefix(prefix).is_some_and(|n| {
            !n.is_empty()
                && n.bytes().all(|b| b.is_ascii_digit())
                && n.parse::<u32>().is_ok_and(|v| (1..=1000).contains(&v))
        })
    })
}

fn log_count(word: &str) -> bool {
    word.strip_prefix('-').is_some_and(|n| {
        !n.is_empty()
            && n.bytes().all(|b| b.is_ascii_digit())
            && n.parse::<u32>().is_ok_and(|n| (1..=1000).contains(&n))
    })
}

#[cfg(test)]
#[path = "pretool_query_tests.rs"]
mod tests;
