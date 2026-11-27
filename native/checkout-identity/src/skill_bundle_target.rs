//! Owner: resolve a flat guidance Markdown link target and produce its relative replacement.
//! Allowed imports: read-only path metadata, DiscoveryFs and PythonText.
//! Forbidden imports: file contents, writes and process execution.
//! Callers/tests: skill bundle link rewrite and migration layout parity.
use crate::{discovery_fs::DiscoveryFs, python_text::PythonText};
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

fn has_scheme(target: &str) -> bool {
    target.split_once(':').is_some_and(|(scheme, _)| {
        scheme.starts_with(|c: char| c.is_ascii_alphabetic())
            && scheme
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"+.-".contains(&c))
    })
}

fn migrated(root: &Path, path: &Path) -> Option<PathBuf> {
    let Ok(relative) = path.strip_prefix(root) else {
        return Some(path.to_owned());
    };
    let parts: Vec<_> = relative.iter().map(|p| p.to_str()).collect::<Option<_>>()?;
    let name = match parts.as_slice() {
        ["workflows", "README.md"] | [.., "SKILL.md"] => return Some(path.to_owned()),
        ["common" | "workflows" | "product-patterns" | "docs", name] | ["platforms", _, name] => {
            *name
        }
        _ => return Some(path.to_owned()),
    };
    let Some(stem) = name.strip_suffix(".md").filter(|stem| !stem.is_empty()) else {
        return Some(path.to_owned());
    };
    if matches!(stem, "." | "..") {
        return None;
    }
    Some(
        path.parent()?
            .join("skills")
            .join(stem)
            .join("references/current-guidance.md"),
    )
}

fn relative(target: &Path, base: &Path) -> Option<String> {
    // os.path.relpath applies abspath to its base, without dereferencing symlinks.
    let base_parts: Vec<_> = base.components().collect();
    if !base.is_absolute() || base_parts.contains(&Component::ParentDir) {
        return None;
    }
    let target_parts: Vec<_> = target.components().collect();
    let shared = target_parts
        .iter()
        .zip(&base_parts)
        .take_while(|(a, b)| a == b)
        .count();
    let mut result = PathBuf::new();
    for _ in &base_parts[shared..] {
        result.push("..");
    }
    for part in &target_parts[shared..] {
        result.push(part.as_os_str());
    }
    Some(if result.as_os_str().is_empty() {
        ".".to_owned()
    } else {
        result.to_str()?.to_owned()
    })
}

pub(super) fn rewrite(
    root: &Path,
    old_parent: &Path,
    new_parent: &Path,
    raw: &str,
) -> Option<String> {
    let link = raw.trim_matches(PythonText::whitespace);
    let anchor = link.find('#').unwrap_or(link.len());
    let (target, rest) = link.split_at(anchor);
    if target.is_empty() || has_scheme(target) {
        return Some(raw.to_owned());
    }
    let target = target.trim_matches(['<', '>']);
    if target.starts_with("//") || !old_parent.is_absolute() || !root.is_absolute() {
        return None;
    }
    let resolved = DiscoveryFs::resolve_allow_missing(&old_parent.join(target))?;
    let metadata = match fs::metadata(&resolved) {
        Ok(meta) => meta,
        Err(e) if matches!(e.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) => {
            return Some(raw.to_owned())
        }
        Err(_) => return None,
    };
    let path = if metadata.is_file() {
        migrated(root, &resolved)?
    } else {
        resolved
    };
    let mut rewritten = relative(&path, new_parent)?;
    rewritten.push_str(rest);
    Some(rewritten)
}
