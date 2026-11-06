//! owner: Verification; allowed imports: next Git reader, Python text, std metadata;
//! forbidden imports: executing suggestions, writes; callers/tests: NextProcess;
//! verification: changed paths and suggested commands against canonical Python.
#[path = "next_verification_git.rs"]
mod git;
#[path = "next_verification_stdin.rs"]
mod input;
use crate::{python_text::PythonText, text::Text};
pub(crate) use input::StdinGuard;
use std::{
    collections::BTreeSet,
    path::{Component, Path},
};

#[derive(Default)]
pub(crate) struct Verification {
    paths: Vec<String>,
    modules: Vec<String>,
    pub(crate) commands: Vec<String>,
}

impl Verification {
    pub(crate) fn discover(project: &Path) -> Option<Self> {
        let paths = changed_paths(&git::VerificationGit::status(project)?);
        let mut modules = BTreeSet::new();
        let mut compile = Vec::new();
        for raw in &paths {
            let normalized = Text::norm_path(raw);
            let path = Path::new(&normalized);
            let Some(stem) = python_stem(&normalized) else {
                continue;
            };
            if reference_is_file(&project.join(path))? {
                compile.push(normalized.clone());
            }
            if path.components().next() == Some(Component::Normal("tests".as_ref()))
                && path.file_name()?.to_str()?.starts_with("test_")
            {
                modules.insert(format!("tests.{stem}"));
                continue;
            }
            for name in [
                format!("test_{}.py", stem.replace('-', "_")),
                format!("test_support_{}.py", stem.replace('-', "_")),
            ] {
                let candidate = project.join("tests").join(name);
                if reference_is_file(&candidate)? {
                    modules.insert(format!("tests.{}", candidate.file_stem()?.to_str()?));
                }
            }
        }
        let modules: Vec<String> = modules.into_iter().collect();
        let mut commands = Vec::new();
        if !compile.is_empty() {
            commands.push(format!(
                "python3 -B -m py_compile {}",
                compile[..compile.len().min(8)].join(" ")
            ));
        }
        if !modules.is_empty() {
            commands.push(format!(
                "PYTHONPATH=tests:scripts python3 -B -m unittest {}",
                modules[..modules.len().min(10)].join(" ")
            ));
        } else {
            for (marker, command) in [
                ("package.json", "npm test"),
                ("Cargo.toml", "cargo test"),
                ("go.mod", "go test ./..."),
                ("Package.swift", "swift test"),
                ("gradlew", "./gradlew test"),
            ] {
                if reference_is_file(&project.join(marker))? {
                    commands.push(command.to_owned());
                    break;
                }
            }
        }
        Some(Self {
            paths,
            modules,
            commands,
        })
    }

    pub(crate) fn json(&self) -> String {
        format!(
            "{{\"changed_paths\": {}, \"matched_test_modules\": {}, \"suggested_commands\": {}}}",
            array(&self.paths),
            array(&self.modules),
            array(&self.commands)
        )
    }
}

fn reference_is_file(path: &Path) -> Option<bool> {
    if path.to_str()?.contains('\0') {
        return Some(false);
    }
    // Path.is_file follows links; ordinary absence, non-directory prefixes,
    // bad descriptors and link loops are false. Other OS errors stay Python's.
    match std::fs::metadata(path) {
        Ok(metadata) => Some(metadata.is_file()),
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT) | Some(libc::ENOTDIR) | Some(libc::EBADF) | Some(libc::ELOOP)
            ) =>
        {
            Some(false)
        }
        Err(_) => None,
    }
}

fn array(values: &[String]) -> String {
    format!(
        "[{}]",
        values
            .iter()
            .map(|s| serde_json::to_string(s).unwrap())
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn python_stem(normalized: &str) -> Option<&str> {
    let name = normalized.rsplit('/').next()?;
    let stem = name.strip_suffix(".py")?;
    if stem.is_empty()
        || (env!("MORU_NEXT_DOT_PREFIX_PY_SUFFIX") != "true" && stem.chars().all(|c| c == '.'))
    {
        None
    } else {
        Some(stem)
    }
}

fn changed_paths(output: &str) -> Vec<String> {
    let mut paths = BTreeSet::new();
    for line in output.split(|c| {
        matches!(
            c,
            '\n' | '\r'
                | '\u{b}'
                | '\u{c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        )
    }) {
        let Some((offset, _)) = line.char_indices().nth(3) else {
            continue;
        };
        let raw = line[offset..].trim_matches(PythonText::whitespace);
        let raw = raw
            .split_once(" -> ")
            .map_or(raw, |(_, name)| name.trim_matches(PythonText::whitespace));
        let raw = raw.trim_matches('"');
        if raw.is_empty() || raw.starts_with(".moru/") {
            continue;
        }
        paths.insert(raw.to_owned());
    }
    paths.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn porcelain_matches_legacy_sort_rename_and_local_state_filter() {
        assert_eq!(
            changed_paths("?? z.py\n M a.py\nR  old.py -> new.py\n?? .moru/state\n?? a.py\n"),
            vec!["a.py".to_owned(), "new.py".to_owned(), "z.py".to_owned()]
        );
    }

    #[test]
    fn unrestricted_paths_and_python_line_breaks() {
        assert_eq!(
            changed_paths(
                "?? ../a.py\n?? -a.py\n?? /a.py\n😀😀😀name.py\u{85}?? b.py\u{1c}?? c.py\u{2028}"
            ),
            vec!["-a.py", "../a.py", "/a.py", "b.py", "c.py", "name.py"]
        );
        assert_eq!(changed_paths("?? a\u{1f}b.py"), vec!["a\u{1f}b.py"]);
    }

    #[test]
    fn pathlib_normalization_and_dot_suffix_follow_builder() {
        assert_eq!(Text::norm_path("./tests//test-a.py/."), "tests/test-a.py");
        assert_eq!(Text::norm_path("//a/../b.py/"), "//a/../b.py");
        assert_eq!(python_stem(".py"), None);
        assert_eq!(
            python_stem("..py"),
            if env!("MORU_NEXT_DOT_PREFIX_PY_SUFFIX") == "true" {
                Some(".")
            } else {
                None
            }
        );
        assert_eq!(python_stem("tests/test-a.py"), Some("test-a"));
        assert_eq!(reference_is_file(Path::new("a\0.py")), Some(false));
    }

    #[test]
    fn literal_unicode_space_and_git_quoting_match_reference_strings() {
        assert_eq!(
            changed_paths("?? \"a b.py\"\n?? 한글.py\n?? \"\\354.py\"\n"),
            vec![
                "\\354.py".to_owned(),
                "a b.py".to_owned(),
                "한글.py".to_owned()
            ]
        );
    }

    #[test]
    fn metadata_follows_links_and_preserves_false_file_predicates() {
        use std::{
            fs,
            os::unix::fs::symlink,
            time::{SystemTime, UNIX_EPOCH},
        };
        let root = std::env::temp_dir().join(format!(
            "moru-next-stat-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("file.py"), b"synthetic\n").unwrap();
        fs::create_dir(root.join("directory")).unwrap();
        symlink("file.py", root.join("linked.py")).unwrap();
        symlink("linked.py", root.join("chain.py")).unwrap();
        symlink("missing.py", root.join("broken.py")).unwrap();
        symlink("loop.py", root.join("loop.py")).unwrap();
        symlink("directory", root.join("directory.py")).unwrap();
        for name in ["file.py", "linked.py", "chain.py"] {
            assert_eq!(reference_is_file(&root.join(name)), Some(true), "{name}");
        }
        for name in [
            "missing.py",
            "broken.py",
            "loop.py",
            "directory",
            "directory.py",
            "file.py/child",
        ] {
            assert_eq!(reference_is_file(&root.join(name)), Some(false), "{name}");
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn uncertain_metadata_error_does_not_become_false() {
        let path = std::env::temp_dir().join("x".repeat(5000));
        assert_eq!(reference_is_file(&path), None);
    }
}
