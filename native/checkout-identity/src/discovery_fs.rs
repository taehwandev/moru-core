//! Owner: read-only project filesystem probes and bounded BFS.
//! Allowed: std, existing libc error constants. Forbidden: policy, writes or caches.
//! Callers/tests: discovery_search; test_native_project_discovery and Rust tests.
use std::{
    collections::VecDeque,
    env, fs,
    path::{Component, Path, PathBuf},
};

const INSTRUCTIONS: &[&str] = &[
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    ".agents/README.md",
    "CONTRIBUTING.md",
];
const MARKERS: &[&str] = &[
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "Package.swift",
    "settings.gradle",
    "settings.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
    "pom.xml",
    "mix.exs",
];
const SKIP: &[&str] = &[
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".gradle",
    ".idea",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
    "DerivedData",
];

pub(crate) struct DiscoveryFs;

impl DiscoveryFs {
    pub(crate) fn lower(text: &str) -> Option<String> {
        // Python 3.9 and Rust use different Unicode versions. Defer non-ASCII
        // case transformations, including Python's contextual final sigma.
        if text
            .chars()
            .any(|c| !c.is_ascii() && c.to_lowercase().to_string() != c.to_string())
        {
            return None;
        }
        Some(text.to_ascii_lowercase())
    }

    pub(crate) fn expand(path: &Path) -> Option<PathBuf> {
        let text = path.to_str()?;
        if text == "~" || text.starts_with("~/") {
            return Some(
                PathBuf::from(env::var_os("HOME")?).join(text.strip_prefix("~/").unwrap_or("")),
            );
        }
        if text.starts_with('~') || text.contains('$') {
            return None;
        }
        Some(path.to_owned())
    }

    pub(crate) fn resolve(path: &Path) -> Option<PathBuf> {
        // Darwin realpath canonicalizes case; Python's resolver preserves the
        // supplied component spelling. Resolve links component by component.
        // Missing, excessive-link and uncertain inputs retain Python handling.
        let absolute = if path.is_absolute() {
            path.to_owned()
        } else {
            env::current_dir().ok()?.join(path)
        };
        let mut pending: VecDeque<_> = absolute
            .components()
            .map(|c| c.as_os_str().to_owned())
            .collect();
        let mut resolved = PathBuf::new();
        let mut links = 0;
        while let Some(part) = pending.pop_front() {
            match Path::new(&part).components().next()? {
                Component::RootDir => resolved = PathBuf::from("/"),
                Component::CurDir => {}
                Component::ParentDir => {
                    resolved.pop();
                }
                Component::Normal(name) => {
                    let next = resolved.join(name);
                    if fs::symlink_metadata(&next).ok()?.is_symlink() {
                        links += 1;
                        if links > 40 {
                            return None;
                        }
                        let target = fs::read_link(next).ok()?;
                        for part in target.components().rev() {
                            pending.push_front(part.as_os_str().to_owned());
                        }
                    } else {
                        resolved = next;
                    }
                }
                _ => return None,
            }
        }
        resolved.to_str()?;
        Some(resolved)
    }

    pub(crate) fn exists(path: &Path) -> Option<bool> {
        match fs::metadata(path) {
            Ok(_) => Some(true),
            Err(e)
                if matches!(
                    e.raw_os_error(),
                    Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP)
                ) =>
            {
                Some(false)
            }
            Err(_) => None,
        }
    }

    pub(crate) fn facts(path: &Path) -> Option<(Vec<String>, Vec<String>)> {
        let probe = |names: &[&str]| -> Option<Vec<String>> {
            let mut found = Vec::new();
            for name in names {
                if Self::exists(&path.join(name))? {
                    found.push((*name).to_owned());
                }
            }
            Some(found)
        };
        Some((probe(INSTRUCTIONS)?, probe(MARKERS)?))
    }

    pub(crate) fn root(start: &Path) -> Option<Option<PathBuf>> {
        let path = Self::resolve(start)?;
        let start = if path.is_file() {
            path.parent()?
        } else {
            &path
        };
        for candidate in start.ancestors() {
            let (files, markers) = Self::facts(candidate)?;
            if !files.is_empty() || !markers.is_empty() {
                return Some(Some(candidate.to_owned()));
            }
        }
        Some(None)
    }

    fn children(path: &Path) -> Option<Vec<PathBuf>> {
        let Ok(entries) = fs::read_dir(path) else {
            return Some(Vec::new());
        };
        let mut names = Vec::new();
        for entry in entries {
            // Python discards all partial results on iteration failure.
            let Ok(entry) = entry else {
                return Some(Vec::new());
            };
            let name = entry.file_name().into_string().ok()?;
            if name.starts_with('.') || SKIP.contains(&name.as_str()) {
                continue;
            }
            match fs::metadata(entry.path()) {
                Ok(meta) if meta.is_dir() => names.push((Self::lower(&name)?, name)),
                _ => {} // A single entry's metadata failure is skipped.
            }
        }
        names.sort_by(|a, b| a.0.cmp(&b.0)); // Stable lowercase, not casefold.
        Some(names.into_iter().map(|(_, name)| path.join(name)).collect())
    }

    pub(crate) fn scan(
        root: &Path,
        depth: usize,
    ) -> Option<Vec<(PathBuf, Vec<String>, Vec<String>)>> {
        let mut queue = VecDeque::from([(Self::resolve(root)?, 0)]);
        let mut records = Vec::new();
        for _ in 0..1500 {
            let Some((current, level)) = queue.pop_front() else {
                break;
            };
            let (files, markers) = Self::facts(&current)?;
            if !files.is_empty() || !markers.is_empty() {
                records.push((current.clone(), files, markers));
            }
            if level < depth {
                queue.extend(
                    Self::children(&current)?
                        .into_iter()
                        .map(|child| (child, level + 1)),
                );
            }
        }
        Some(records)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn case_contract_is_conservative() {
        assert_eq!(DiscoveryFs::lower("AbC 한글 ß"), Some("abc 한글 ß".into()));
        for name in ["Σ", "ΟΣ", "İ", "É"] {
            assert!(DiscoveryFs::lower(name).is_none());
        }
    }
}
