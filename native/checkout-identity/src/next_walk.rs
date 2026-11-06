//! owner: NextWalk; allowed imports: std and local file metadata;
//! forbidden imports: writes, following symlinks, registry decisions;
//! callers/tests: Candidates; verification: sorted custom/worker/nested checkout discovery.
use std::{
    collections::BTreeSet,
    fs,
    path::{Path, PathBuf},
};
pub(super) struct NextWalk {
    pub(super) candidates: Vec<PathBuf>,
    pub(super) workers: Vec<PathBuf>,
    pub(super) complete: bool,
}
impl NextWalk {
    pub(super) fn read(state: &Path, names: &BTreeSet<String>) -> Option<Self> {
        let mut result = Self {
            candidates: Vec::new(),
            workers: Vec::new(),
            complete: true,
        };
        if names.is_empty() {
            return Some(result);
        }
        let worker_root = state.join("workers");
        let mut pending = vec![(state.to_owned(), 0usize)];
        let mut visited = 0;
        while let Some((directory, depth)) = pending.pop() {
            visited += 1;
            if visited > 100_000 || depth > 256 {
                return None;
            }
            if fs::symlink_metadata(&directory).is_ok_and(|m| m.file_type().is_symlink()) {
                continue;
            }
            let entries = match fs::read_dir(&directory) {
                Ok(entries) => entries,
                Err(_) => {
                    if !directory.starts_with(&worker_root) {
                        result.complete = false;
                    }
                    continue;
                }
            };
            let mut directories = Vec::new();
            let mut files = Vec::new();
            let mut failed = false;
            for entry in entries {
                let entry = match entry {
                    Ok(entry) => entry,
                    Err(_) => {
                        if !directory.starts_with(&worker_root) {
                            result.complete = false;
                        }
                        failed = true;
                        break;
                    }
                };
                let name = entry.file_name().to_str()?.to_owned();
                let path = entry.path();
                let meta = match fs::symlink_metadata(&path) {
                    Ok(meta) => meta,
                    // Python may retain cached directory type even after removal.
                    Err(_) => return None,
                };
                if meta.file_type().is_symlink() {
                    continue;
                }
                if meta.is_dir() {
                    if fs::symlink_metadata(path.join(".git")).is_err() {
                        directories.push(path);
                    }
                } else if names.contains(&name) {
                    files.push(path);
                }
            }
            if failed {
                continue;
            }
            files.sort();
            for file in files {
                result.file(&file, &worker_root)?;
            }
            directories.sort();
            pending.extend(directories.into_iter().rev().map(|path| (path, depth + 1)));
        }
        Some(result)
    }

    fn file(&mut self, path: &Path, worker_root: &Path) -> Option<()> {
        match fs::symlink_metadata(path) {
            Ok(meta) if meta.is_file() => {}
            Ok(_) => return Some(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Some(()),
            // Path.is_file suppresses different OSErrors across Python versions.
            Err(_) => return None,
        }
        match path.canonicalize() {
            Ok(resolved) => {
                // A concurrently inserted directory link needs the compatibility path.
                if resolved != path {
                    return None;
                }
                if path.starts_with(worker_root) {
                    self.workers.push(resolved);
                } else {
                    self.candidates.push(resolved);
                }
            }
            Err(_) => self.complete = false,
        }
        Some(())
    }
}

#[cfg(test)]
#[path = "next_walk_tests.rs"]
mod tests;
