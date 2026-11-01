//! Pure changed-file verification suggestions. Never runs suggested commands.
use crate::{callback_state::LocalState as State, gitrun::GitRead, text::Text};
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
        let paths = changed_paths(&GitRead::status(project.to_str()?)?)?;
        let mut modules = BTreeSet::new();
        let mut compile = Vec::new();
        for raw in &paths {
            let path = Path::new(raw);
            State::safe_path(project, &project.join(path))?;
            if path.extension().and_then(|v| v.to_str()) != Some("py") {
                continue;
            }
            if project.join(path).is_file() {
                compile.push(Text::norm_path(raw));
            }
            let stem = path.file_stem()?.to_str()?;
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
                State::safe_path(project, &candidate)?;
                if candidate.is_file() {
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
                State::safe_path(project, &project.join(marker))?;
                if project.join(marker).is_file() {
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

fn changed_paths(output: &str) -> Option<Vec<String>> {
    let mut paths = BTreeSet::new();
    for line in output.lines() {
        if !line.chars().take(3).all(|c| c.is_ascii()) {
            return None;
        }
        if line.len() < 4 {
            continue;
        }
        let raw = Text::py_strip(&line[3..]);
        let raw = raw
            .split_once(" -> ")
            .map_or(raw, |(_, name)| Text::py_strip(name));
        let raw = raw.trim_matches('"');
        if raw.is_empty() || raw.starts_with(".moru/") {
            continue;
        }
        if raw.starts_with('-')
            || Path::new(raw).is_absolute()
            || !raw
                .chars()
                .all(|c| c.is_alphanumeric() || "_./- \\".contains(c))
            || Path::new(raw)
                .components()
                .any(|c| c == Component::ParentDir)
        {
            return None;
        }
        paths.insert(raw.to_owned());
    }
    Some(paths.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn porcelain_matches_legacy_sort_rename_and_local_state_filter() {
        assert_eq!(
            changed_paths("?? z.py\n M a.py\nR  old.py -> new.py\n?? .moru/state\n?? a.py\n"),
            Some(vec![
                "a.py".to_owned(),
                "new.py".to_owned(),
                "z.py".to_owned()
            ])
        );
    }

    #[test]
    fn uncertain_paths_stay_with_python() {
        for output in [
            "?? ../a.py\n",
            "?? -a.py\n",
            "?? /a.py\n",
            "?? a\u{1c}b.py\n",
        ] {
            assert!(changed_paths(output).is_none(), "{output}");
        }
    }

    #[test]
    fn literal_unicode_space_and_git_quoting_match_reference_strings() {
        assert_eq!(
            changed_paths("?? \"a b.py\"\n?? 한글.py\n?? \"\\354.py\"\n"),
            Some(vec![
                "\\354.py".to_owned(),
                "a b.py".to_owned(),
                "한글.py".to_owned()
            ])
        );
    }
}
