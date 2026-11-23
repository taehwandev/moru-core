//! owner: lazy discovery of linked worktree and sibling repository candidates;
//! allowed imports: guarded metadata reads, existing candidate ranking, std and JSON;
//! forbidden imports: Git writes, session authority, proof selection and providers;
//! callers/tests: private discover-reuse-roots probe and document reuse conformance;
//! verification: staged discovery, metadata aliases, bounds, recency and exclusions.
use super::DocTranscript;
use crate::text::Text;
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::{Component, Path, PathBuf},
};

const MAX_ENTRIES: usize = 256;
const MAX_LINK_BYTES: u64 = 64 * 1024;

impl DocTranscript {
    pub(crate) fn discover_reuse_roots(payload: &Value) -> Option<Value> {
        let path = canonical_path(Path::new(payload.get("path")?.as_str()?))?;
        let excluded = payload.get("excluded")?.as_array()?;
        let limit = usize::try_from(payload.get("limit")?.as_u64()?).ok()?;
        if excluded.len() > MAX_ENTRIES || limit > 8 {
            return None;
        }
        let excluded = excluded
            .iter()
            .map(|value| Some(Path::new(value.as_str()?)))
            .collect::<Option<Vec<_>>>()?;
        let (workspace, candidates) = match payload.get("phase")?.as_str()? {
            "worktrees" => Self::worktree_candidates(&path)?,
            "siblings" => (None, sibling_candidates(&path)?),
            _ => return None,
        };
        let roots = Self::rank_roots(candidates.iter().map(PathBuf::as_path), &excluded, limit)?;
        Some(json!([workspace, roots]))
    }

    fn worktree_candidates(project: &Path) -> Option<(Option<PathBuf>, Vec<PathBuf>)> {
        let marker = project.join(".git");
        let common = match metadata(&marker)? {
            Some(meta) if meta.is_file() => {
                let pointer = Self::read_link_text(&marker)?;
                let (_, git_dir) = pointer.split_once("gitdir:")?;
                let git_dir = project.join(Text::py_strip(git_dir));
                let pointer = Self::read_link_text(&git_dir.join("commondir"))?;
                canonical_path(&git_dir.join(Text::py_strip(&pointer)))?
            }
            Some(meta) if meta.is_dir() => canonical_path(&marker)?,
            _ => return Some((None, Vec::new())),
        };
        let mut candidates = Vec::new();
        let mut workspace = None;
        if common.file_name()?.to_str()? == ".git" {
            let main = common.parent()?;
            workspace = main.parent().map(Path::to_path_buf);
            candidates.push(main.to_path_buf());
        }
        let directory = common.join("worktrees");
        for entry in directory_entries(&directory)? {
            let link = entry.join("gitdir");
            if metadata(&link)?.is_some() {
                let named = Self::read_link_text(&link)?;
                let parent = Path::new(Text::py_strip(&named)).parent()?;
                candidates.push(canonical_path(parent)?);
            }
        }
        Some((workspace, candidates))
    }

    fn read_link_text(path: &Path) -> Option<String> {
        let meta = fs::metadata(path).ok()?;
        if !meta.is_file() || meta.len() > MAX_LINK_BYTES {
            return None;
        }
        let mut text = String::new();
        Self::open(path, &meta)?
            .ok()?
            .take(MAX_LINK_BYTES + 1)
            .read_to_string(&mut text)
            .ok()?;
        (text.len() as u64 <= MAX_LINK_BYTES).then(|| Text::universal_newlines(&text))
    }
}

fn sibling_candidates(workspace: &Path) -> Option<Vec<PathBuf>> {
    let mut candidates = Vec::new();
    for entry in directory_entries(workspace)? {
        if metadata(&entry.join(".git"))?.is_some() {
            candidates.push(canonical_path(&entry)?);
        }
    }
    Some(candidates)
}

fn directory_entries(path: &Path) -> Option<Vec<PathBuf>> {
    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(error) if absent(&error) => return Some(Vec::new()),
        Err(_) => return None,
    };
    let entries = entries
        .take(MAX_ENTRIES + 1)
        .map(|entry| entry.map(|entry| entry.path()))
        .collect::<Result<Vec<_>, _>>()
        .ok()?;
    (entries.len() <= MAX_ENTRIES).then_some(entries)
}

fn metadata(path: &Path) -> Option<Option<fs::Metadata>> {
    match fs::metadata(path) {
        Ok(metadata) => Some(Some(metadata)),
        Err(error) if absent(&error) => Some(None),
        Err(_) => None,
    }
}

fn absent(error: &std::io::Error) -> bool {
    matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory)
}

fn canonical_path(path: &Path) -> Option<PathBuf> {
    if !path.is_absolute() || path.to_str()?.starts_with("//") {
        return None;
    }
    let mut lexical = PathBuf::from("/");
    for component in path.components() {
        match component {
            Component::Normal(name) => lexical.push(name),
            Component::ParentDir => {
                lexical.pop();
            }
            _ => {}
        }
    }
    // Defer spelling changes and symlinks to pathlib, which can differ from
    // canonicalize even when both spellings address the same directory.
    let actual = fs::canonicalize(path).ok()?;
    (actual.as_os_str() == lexical.as_os_str()).then_some(lexical)
}
