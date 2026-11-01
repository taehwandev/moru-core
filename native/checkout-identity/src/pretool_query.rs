//! Closed plain-query grammar. No shell parsing, execution, or policy mutation.
use std::path::Path;

pub(crate) fn executable(command: &str) -> Option<&str> {
    if let Some(query) = crate::pretool_files::FileQuery::command(command) {
        return Some(query.executable());
    }
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
        | ["status", "--short" | "--porcelain" | "--porcelain=v1", "--branch"]
        | ["status", "--branch", "--short" | "--porcelain" | "--porcelain=v1"]
        | ["remote", "-v"]
        | ["diff", "--stat" | "--check" | "--name-only" | "--name-status" | "--numstat" | "--exit-code"]
        | ["diff", "--cached", "--stat" | "--check" | "--name-only" | "--name-status" | "--numstat"]
        | ["rev-parse", "HEAD" | "--show-toplevel"]
        | ["branch", "--show-current"]
        | ["ls-files"]
        | ["ls-files", "--cached" | "--stage"]
        | ["ls-files", "--others", "--exclude-standard"]
        | ["log", "--oneline"]
        | ["show", "--stat" | "--name-only"]
        | ["tag", "--list"]
        | ["tag", "--list", "--sort=-version:refname"] => Some("git"),
        ["log", count, "--oneline"] | ["log", "--oneline", count] if log_count(count) => {
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

fn log_count(word: &str) -> bool {
    word.strip_prefix('-').is_some_and(|n| {
        !n.is_empty()
            && n.bytes().all(|b| b.is_ascii_digit())
            && n.parse::<u32>().is_ok_and(|n| (1..=1000).contains(&n))
    })
}

#[cfg(test)]
mod tests {
    use super::executable;

    #[test]
    fn closed_queries_only() {
        for command in [
            "pwd",
            "git status --short",
            "git status --short --branch",
            "git status --branch --porcelain=v1",
            "git remote -v",
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
            "git remote -v add origin nowhere",
            "git remote update",
            "git status --short --branch --ignored",
            "pwd$(touch x)",
        ] {
            assert!(executable(command).is_none(), "{command}");
        }
    }

    #[test]
    fn file_queries_reject_generated_shell_and_option_neighbors() {
        let accepted = [
            "rg --files",
            "rg --files src",
            "rg -n TODO",
            "rg -n TODO notes.txt",
            "cat notes.txt",
            "cat -n notes.txt src/code.py",
            "head notes.txt",
            "head -n 0 notes.txt",
            "cat 한글.txt",
            "cat '한글 메모.txt'",
            "head -n 20 \"한글 메모.txt\"",
            "tail notes.txt",
            "ls",
            "ls -la",
            "ls -lh notes.txt",
            "ls -lah '소스 폴더'",
            "tail -n 0 notes.txt",
            "tail -n 1000000 '한글 메모.txt'",
            "wc notes.txt",
            "wc -l notes.txt",
            "wc -m '한글 메모.txt'",
            "sed -n '1,120p' notes.txt",
            "sed -n \"42p\" notes.txt",
            "sed -n 1,10p notes.txt",
            "rg --files '소스 폴더'",
            "rg -n TODO \"소스 폴더/한글 메모.txt\"",
        ];
        for command in accepted {
            assert!(executable(command).is_some(), "{command}");
            for tail in [
                "; touch x",
                " && touch x",
                " | cat",
                " > x",
                " 2>x",
                "$(touch x)",
                "`touch x`",
                " # comment",
                " --pre=evil",
                " --output=x",
                " -i",
                " \"$x\"",
            ] {
                assert!(
                    executable(&format!("{command}{tail}")).is_none(),
                    "{command}{tail}"
                );
            }
            for control in (0u8..=31)
                .filter(|c| *c != b'\t')
                .chain(std::iter::once(127))
            {
                assert!(executable(&format!("{command}{}", char::from(control))).is_none());
            }
        }
        for command in [
            "rg -n --pre=evil notes.txt",
            "rg --files --hidden",
            "rg -n a.* notes.txt",
            "cat -u notes.txt",
            "cat ../notes.txt",
            "head -n -1 notes.txt",
            "head -n 1000001 notes.txt",
            "head -n 4294967296 notes.txt",
            "head -n +1 notes.txt",
            "head -c 20 notes.txt",
            "tail -f notes.txt",
            "tail -n +1 notes.txt",
            "tail -n 1000001 notes.txt",
            "wc -l -w notes.txt",
            "wc --files0-from=list",
            "ls -R",
            "ls -l -a",
            "ls --color=always",
            "sed -i '1p' notes.txt",
            "sed -n '1,5p;w written' notes.txt",
            "sed -n '1,5w written' notes.txt",
            "sed -n '1,5e' notes.txt",
            "sed -n '$p' notes.txt",
            "sed -n '0p' notes.txt",
            "sed -n '5,1p' notes.txt",
            "sed -n '1,1000001p' notes.txt",
            "sed -n '1,5p' -i notes.txt",
            "cat",
            "head",
            "rg -n",
            "rg",
            "cat 'notes'.txt",
            "cat '-n' notes.txt",
            "'cat' notes.txt",
            "cat \"$HOME/notes.txt\"",
            "cat -n",
            "head -n 20",
            "cat -",
        ] {
            assert!(executable(command).is_none(), "{command}");
        }
        let twenty = format!("cat {}", vec!["notes.txt"; 19].join(" "));
        assert!(executable(&twenty).is_some());
        assert!(executable(&format!("{twenty} notes.txt")).is_none());
    }
}
