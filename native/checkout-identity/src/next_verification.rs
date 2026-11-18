//! owner: Verification; allowed imports: next Git reader, Python text, std metadata;
//! forbidden imports: executing suggestions, writes; callers/tests: NextProcess;
//! verification: changed paths and suggested commands against canonical Python.
#[path = "next_verification_git.rs"]
mod git;
#[path = "next_verification_stdin.rs"]
mod input;
#[path = "next_verification_render.rs"]
mod render;
#[path = "next_verification_selectors.rs"]
mod selectors;
use crate::{python_text::PythonText, text::Text};
pub(crate) use input::StdinGuard;
use render::VerificationRender;
pub(crate) use selectors::VerificationSelectors;
use serde_json::Value;
use std::{
    collections::BTreeSet,
    path::{Component, Path},
};

pub(super) const RUNNER_SELECTOR_LIMIT: usize = 64;
const COMPILE_TARGET_LIMIT: usize = 64;
const FALLBACK_MARKERS: [(&str, &str); 5] = [
    ("package.json", "npm test"),
    ("Cargo.toml", "cargo test"),
    ("go.mod", "go test ./..."),
    ("Package.swift", "swift test"),
    ("gradlew", "./gradlew test"),
];

#[derive(Default, Clone)]
pub(crate) struct Verification {
    paths: Vec<String>,
    modules: Vec<String>,
    pub(crate) selectors: Vec<String>,
    pub(crate) next_batch: Vec<String>,
    pub(crate) remaining_selectors: Vec<String>,
    pub(crate) omissions: Vec<Value>,
    pub(crate) coverage_note: String,
    pub(crate) commands: Vec<String>,
    pub(crate) verify_command: Option<String>,
    pub(crate) batch_status: Option<String>,
}

#[derive(Default)]
struct TargetCollector {
    compile: BTreeSet<String>,
    modules: BTreeSet<String>,
    selectors: BTreeSet<String>,
    omissions: Vec<Value>,
    seen: BTreeSet<(String, String, String)>,
}

impl TargetCollector {
    fn record_selector(
        &mut self,
        tests_dir: &Path,
        rel_under_tests: &[&str],
        omission_path: &str,
    ) -> Option<bool> {
        match VerificationSelectors::selector_eligibility(
            tests_dir,
            rel_under_tests,
            reference_is_file,
        )? {
            Ok(sel) => {
                self.modules.insert(format!("tests.{sel}"));
                self.selectors.insert(sel);
                Some(true)
            }
            Err(reason) => {
                VerificationRender::push_omission(
                    &mut self.omissions,
                    &mut self.seen,
                    "unsupported_test_file",
                    omission_path,
                    reason,
                    None,
                );
                Some(false)
            }
        }
    }
}

impl Verification {
    pub(crate) fn discover(project: &Path) -> Option<Self> {
        let paths = changed_paths(&git::VerificationGit::status(project)?);
        let collected = Self::collect_targets(project, &paths)?;
        Self::from_collected(project, paths, collected)
    }

    fn from_collected(
        project: &Path,
        paths: Vec<String>,
        mut collected: TargetCollector,
    ) -> Option<Self> {
        // Batches above 64 selectors require multi-batch Python verification receipt handling.
        if collected.selectors.len() > RUNNER_SELECTOR_LIMIT {
            return None;
        }
        let selectors: Vec<String> = collected.selectors.into_iter().collect();
        let modules: Vec<String> = collected.modules.into_iter().collect();
        let compile: Vec<String> = collected.compile.into_iter().collect();
        let compile_batch_len = compile.len().min(COMPILE_TARGET_LIMIT);
        if compile.len() > COMPILE_TARGET_LIMIT {
            VerificationRender::push_omission(
                &mut collected.omissions,
                &mut collected.seen,
                "compile_limit",
                "",
                "exceeds_compile_64_target_limit",
                Some(compile.len() - COMPILE_TARGET_LIMIT),
            );
        }
        let fallback = if modules.is_empty() {
            fallback_command(project)?
        } else {
            None
        };
        let commands =
            VerificationRender::build_commands(&compile[..compile_batch_len], &modules, fallback);
        let coverage_note =
            VerificationRender::coverage_note(!selectors.is_empty(), !compile.is_empty());
        Some(Self {
            paths,
            modules,
            next_batch: selectors.clone(),
            selectors,
            remaining_selectors: Vec::new(),
            omissions: collected.omissions,
            coverage_note,
            commands,
            verify_command: None,
            batch_status: None,
        })
    }

    fn collect_targets(project: &Path, paths: &[String]) -> Option<TargetCollector> {
        let mut collected = TargetCollector::default();
        let tests_dir = project.join("tests");
        for raw in paths {
            let normalized = Text::norm_path(raw);
            let path = Path::new(&normalized);
            let Some(stem) = python_stem(&normalized) else {
                continue;
            };
            let is_file = reference_is_file(&project.join(path))?;
            if is_file {
                collected.compile.insert(normalized.clone());
            }
            let comps: Vec<&str> = path
                .components()
                .filter_map(|c| match c {
                    Component::Normal(s) => s.to_str(),
                    _ => None,
                })
                .collect();
            let file_name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
            if comps.first() == Some(&"tests") && file_name.starts_with("test_") && comps.len() >= 2
            {
                collected.record_selector(&tests_dir, &comps[1..], &normalized)?;
                continue;
            }
            let mut matched = false;
            for name in [
                format!("test_{}.py", stem.replace('-', "_")),
                format!("test_support_{}.py", stem.replace('-', "_")),
            ] {
                let candidate = tests_dir.join(&name);
                if VerificationSelectors::path_exists_lstat(&candidate)?
                    && collected.record_selector(&tests_dir, &[&name], &format!("tests/{name}"))?
                {
                    matched = true;
                }
            }
            if !matched && is_file && file_name != "__init__.py" {
                VerificationRender::push_omission(
                    &mut collected.omissions,
                    &mut collected.seen,
                    "unmatched_python_file",
                    &normalized,
                    "no_matching_test_file",
                    None,
                );
            }
        }
        Some(collected)
    }

    pub(crate) fn apply_active_verify(
        &mut self,
        launcher: &str,
        project: &str,
        rules: &str,
        evidence: &str,
    ) -> Option<String> {
        VerificationRender::apply_active_verify(self, launcher, project, rules, evidence)
    }

    pub(crate) fn json(&self) -> String {
        VerificationRender::json(self)
    }
}

fn fallback_command(project: &Path) -> Option<Option<&'static str>> {
    for (marker, command) in FALLBACK_MARKERS {
        if reference_is_file(&project.join(marker))? {
            return Some(Some(command));
        }
    }
    Some(None)
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

    #[test]
    fn selector_count_above_64_falls_back_to_none() {
        let build = |count: usize| {
            let mut collector = TargetCollector::default();
            for i in 0..count {
                collector.selectors.insert(format!("test_case_{i:02}"));
                collector.modules.insert(format!("tests.test_case_{i:02}"));
            }
            Verification::from_collected(Path::new("/project"), Vec::new(), collector)
        };
        assert_eq!(build(RUNNER_SELECTOR_LIMIT).unwrap().selectors.len(), 64);
        assert!(build(RUNNER_SELECTOR_LIMIT + 1).is_none());
    }
}
