//! owner: WorkerScope; allowed imports: std, local path guard, Python whitespace;
//! forbidden imports: writes/reservations; callers/tests: NextSession;
//! verification: worker shape, symlink refusal and whitespace environment parity.
use crate::{callback_state::LocalState as State, python_text::PythonText};
use std::{
    env, fs,
    path::{Component, Path, PathBuf},
};
pub(super) enum WorkerScope {
    Parent,
    Invalid,
    Selected(PathBuf),
}
impl WorkerScope {
    pub(super) fn current(project: &Path) -> Option<Self> {
        let raw = match env::var("MORU_WORKER_EVIDENCE") {
            Ok(raw) => raw,
            Err(env::VarError::NotPresent) => return Some(Self::Parent),
            Err(_) => return None,
        };
        Self::parse(project, &raw, &env::current_dir().ok()?)
    }

    fn parse(project: &Path, raw: &str, cwd: &Path) -> Option<Self> {
        let raw = raw.trim_matches(PythonText::whitespace);
        if raw.is_empty() {
            return Some(Self::Parent);
        }
        let path = if raw == "~" || raw.starts_with("~/") {
            let home = PathBuf::from(env::var_os("HOME")?);
            if raw == "~" {
                home
            } else {
                home.join(&raw[2..])
            }
        } else if raw.starts_with('~') {
            return None;
        } else {
            PathBuf::from(raw)
        };
        let path = if path.is_absolute() {
            path
        } else {
            cwd.join(path)
        };
        if path.to_str()?.starts_with("//") || path.to_str()?.contains('\0') {
            return None;
        }
        if path.components().any(|c| c == Component::ParentDir) {
            return None;
        }
        let path: PathBuf = path
            .components()
            .filter(|c| *c != Component::CurDir)
            .collect();
        let workers = project.join(".moru/workers");
        // A linked state root violates the lexical worker-root identity contract.
        let state = project.join(".moru");
        if state.canonicalize().ok()? != state {
            return Some(Self::Invalid);
        }
        for checked in [&workers, path.parent()?, &path] {
            match fs::symlink_metadata(checked) {
                Ok(meta) if meta.file_type().is_symlink() => return Some(Self::Invalid),
                Ok(_) => {}
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(_) => return None,
            }
        }
        // For missing paths this proves strict=False resolution without guessing through links.
        State::safe_path(Path::new("/"), &workers)?;
        State::safe_path(Path::new("/"), &path)?;
        let selected = match path.canonicalize() {
            Ok(path) => path,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => path,
            Err(_) => return None,
        };
        let Ok(relative) = selected.strip_prefix(&workers) else {
            return Some(Self::Invalid);
        };
        if relative.components().count() != 2 || relative.file_name()? != "preflight.json" {
            return Some(Self::Invalid);
        }
        Some(Self::Selected(selected))
    }
}

#[cfg(test)]
#[path = "next_worker_scope_tests.rs"]
mod tests;
