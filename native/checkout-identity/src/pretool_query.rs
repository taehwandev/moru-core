//! Closed plain-query grammar. No shell parsing, execution, or policy mutation.
use std::path::Path;

pub(crate) fn executable(command: &str) -> Option<&str> {
    if !command.is_ascii()
        || command.bytes().any(|b| b < 32 && b != b'\t')
        || command
            .bytes()
            .any(|b| b"'\"\\$`;&|<>#(){}*?!~".contains(&b))
    {
        return None;
    }
    let tokens: Vec<_> = command.split_ascii_whitespace().collect();
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
        ["status", "--short" | "--porcelain" | "--porcelain=v1"]
        | ["diff", "--stat" | "--check" | "--name-only" | "--numstat" | "--exit-code"]
        | ["diff", "--cached", "--stat" | "--check" | "--name-only" | "--numstat"]
        | ["rev-parse", "HEAD" | "--show-toplevel"]
        | ["branch", "--show-current"] => Some("git"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::executable;

    #[test]
    fn closed_queries_only() {
        for command in [
            "pwd",
            "git status --short",
            "git diff --cached --check",
            "git rev-parse HEAD",
        ] {
            assert!(executable(command).is_some(), "{command}");
        }
        for command in [
            "git diff --stat --output=x",
            "git -c core.pager=evil status --short",
            "git status --short; touch x",
            "git status --short\n",
            "git status --short > x",
            "git status --short | cat",
            "git status --short # note",
            "GIT_DIR=x git status --short",
            "git status '--short'",
            "/usr/bin/git status --short",
            "git worktree remove x",
            "pwd$(touch x)",
        ] {
            assert!(executable(command).is_none(), "{command}");
        }
    }
}
