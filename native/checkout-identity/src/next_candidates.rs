//! owner: Candidates; allowed imports: std, SHA256, local state and shared JSON;
//! forbidden imports: writes/session decisions; callers/tests: NextSession;
//! verification: process parity of complete canonical registry bindings.
#[path = "next_walk.rs"]
mod walk;
use super::NextSession;
use crate::{callback_state::LocalState as State, python_json::Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};
pub(super) struct Candidates;
impl Candidates {
    pub(super) fn select(
        project: &Path,
        state: &Path,
        bindings: &BTreeMap<String, Value>,
    ) -> Option<(Vec<PathBuf>, Vec<PathBuf>, bool)> {
        // Python's run-local containment uses the lexical .moru/runs root.
        if let Some(paths) = (state == project.join(".moru"))
            .then(|| Self::read(project, bindings))
            .flatten()
        {
            return Some((
                paths.into_iter().map(|(path, _)| path).collect(),
                Vec::new(),
                true,
            ));
        }
        let names: BTreeSet<String> = bindings
            .values()
            .map(|run| NextSession::text(run.get("evidence_name")))
            .filter(|name| !name.is_empty() && name != "." && !name.contains('/'))
            .collect();
        let result = walk::NextWalk::read(state, &names)?;
        Some((result.candidates, result.workers, result.complete))
    }
    pub(super) fn key(project: &Path, path: &Path) -> Option<String> {
        let text = path.strip_prefix(project).unwrap_or(path).to_str()?;
        let text = if text.is_empty() { "." } else { text };
        Some(format!("{:x}", Sha256::digest(text.as_bytes())))
    }

    pub(super) fn read(
        project: &Path,
        bindings: &BTreeMap<String, Value>,
    ) -> Option<Vec<(PathBuf, String)>> {
        let state = project.join(".moru");
        let runs = state.join("runs");
        Self::directory(&state, false)?;
        Self::directory(&runs, true)?;
        let mut paths = Vec::new();
        for (key, run) in bindings {
            let id = NextSession::text(run.get("run_id"));
            if id.len() != 32
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
            {
                return None;
            }
            let name = NextSession::text(run.get("evidence_name"));
            if name.is_empty()
                || name == "."
                || name == ".."
                || name.contains('/')
                || name.contains('\0')
            {
                return None;
            }
            let directory = runs.join(id);
            Self::directory(&directory, true)?;
            let path = directory.join(name);
            State::safe_path(project, &path)?;
            if !fs::symlink_metadata(&path).ok()?.is_file() {
                return None;
            }
            let path = path.canonicalize().ok()?;
            if Self::key(project, &path)? != *key {
                return None;
            }
            paths.push((path, key.clone()));
        }
        paths.sort_by(|a, b| a.0.cmp(&b.0));
        Some(paths)
    }

    fn directory(path: &Path, nested: bool) -> Option<()> {
        if !fs::symlink_metadata(path).ok()?.is_dir() {
            return None;
        }
        if nested {
            match fs::symlink_metadata(path.join(".git")) {
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                _ => return None,
            }
        }
        drop(fs::read_dir(path).ok()?);
        Some(())
    }
}
