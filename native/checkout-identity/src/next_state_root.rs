//! owner: NextStateRoot; allowed imports: std/local path guard; forbidden imports:
//! writes/global-state remapping; callers/tests: NextSession; verification: linked roots.
use crate::callback_state::LocalState as State;
use std::{
    fs,
    path::{Path, PathBuf},
};
pub(super) struct NextStateRoot;
impl NextStateRoot {
    pub(super) fn resolve(project: &Path) -> Option<Option<PathBuf>> {
        let lexical = project.join(".moru");
        match fs::symlink_metadata(&lexical) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Some(None),
            Err(_) => return None,
            Ok(_) => {}
        }
        // Dangling, looping and non-directory roots require the reference path.
        let resolved = lexical.canonicalize().ok()?;
        if !resolved.is_dir() {
            return None;
        }
        State::safe_path(Path::new("/"), &resolved)?;
        Some(Some(resolved))
    }
}

#[cfg(test)]
#[path = "next_state_root_tests.rs"]
mod tests;
