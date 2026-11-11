use super::executable;

#[test]
fn diff_plain_cached_and_literal_paths_are_closed_read_queries() {
    for command in [
        "git diff",
        "git diff --cached",
        "git diff --cached --exit-code",
        "git diff -- README.md",
        "git diff --cached -- README.md src/lib.rs",
        "git diff --stat -- src",
        "git diff --cached --numstat -- .",
        "git diff --name-status -- '소스 폴더/파일.rs'",
        "git diff --check -- /tmp/source.rs",
    ] {
        assert_eq!(executable(command), Some("git"), "{command}");
    }
    for command in [
        "git diff --output=x",
        "git diff --cached --output=x -- README.md",
        "git diff --ext-diff -- README.md",
        "git diff --textconv -- README.md",
        "git diff -- --output=x",
        "git diff -- --ext-diff",
        "git diff --cached --cached",
        "git diff --",
        "git diff -- ../README.md",
        "git diff -- ':(top,literal)README.md'",
        "git diff -- README.md; touch written",
        "git diff -- README.md > written",
        "git diff -- README.md && touch written",
        "git diff -- README.md # note",
        "git diff -- \"$FILE\"",
        "git diff -- '*.rs'",
        "git diff -- 'a|b.rs'",
    ] {
        assert!(executable(command).is_none(), "{command}");
    }
}

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

#[test]
fn rg_regex_globs_keep_shell_and_preprocessors_out() {
    for command in [
        "rg -n 'foo|bar' notes.txt",
        "rg -n '^def [a-z_]+' notes.txt",
        "rg --files -g '*.py' src",
        "rg --files --glob='*.rs' src",
        "rg -n -g '*.py' 'def |class ' src",
        "rg -n 'foo|bar' src --glob '*.rs'",
        "rg -n 'foo|bar' -- src",
    ] {
        assert_eq!(executable(command), Some("rg"), "{command}");
    }
    for command in [
        "rg -n foo|touch marker",
        "rg -n 'foo'bar notes.txt",
        "rg -n \"$PATTERN\" notes.txt",
        "rg -n 'foo' --pre=evil notes.txt",
        "rg --files -g --pre=evil",
        "rg --files --glob='--pre=evil'",
        "rg -n '`touch marker`' notes.txt",
        "rg -n foo notes.txt > marker",
        "rg -n foo notes.txt --pre evil",
        "rg --files -g '*.py' && touch marker",
    ] {
        assert!(executable(command).is_none(), "{command}");
    }
}
