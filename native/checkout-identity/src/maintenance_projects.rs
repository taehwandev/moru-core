//! owner: read-only maintenance checkout enumeration; allowed: filesystem metadata and JSON;
//! forbidden: root discovery outside supplied paths, lock creation, maintenance and deletion;
//! callers/tests: managed_projects and native maintenance ordering/privacy parity.
use crate::discovery_fs::DiscoveryFs;
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
};

const MAX_ENTRIES: usize = 4096;

pub(super) struct MaintenanceProjects;

impl MaintenanceProjects {
    pub(super) fn scan(request: &Value) -> Option<Value> {
        let mut candidates = Self::paths(request.get("candidates")?)?;
        let roots = Self::paths(request.get("search_roots")?)?;
        let mut remaining = MAX_ENTRIES.checked_sub(candidates.len() + roots.len())?;
        for root in roots {
            if !Self::is_dir(&root)? {
                continue;
            }
            if Self::has_runs(&root)? {
                candidates.push(root.clone());
            }
            for child in Self::entries(&root, &mut remaining)? {
                let name = child.file_name()?.to_str()?;
                if !name.starts_with('.')
                    && !matches!(name, "node_modules" | "build" | "dist" | "target")
                    && Self::is_dir(&child)?
                    && Self::has_runs(&child)?
                {
                    candidates.push(child);
                }
            }
        }
        let mut seen = HashSet::new();
        let mut checkouts = Vec::new();
        for candidate in candidates {
            let worktree_dir = candidate.join(".moru/worktrees");
            let worktrees = Self::entries(&worktree_dir, &mut remaining)?;
            for checkout in std::iter::once(candidate).chain(worktrees) {
                if !Self::is_dir(&checkout)? {
                    continue;
                }
                let resolved = DiscoveryFs::resolve(&checkout)?;
                if Self::is_dir(&resolved.join(".moru"))? && seen.insert(resolved.clone()) {
                    checkouts.push(resolved.to_str()?.to_owned());
                }
            }
        }
        Some(json!({"checkouts": checkouts}))
    }

    fn paths(value: &Value) -> Option<Vec<PathBuf>> {
        value
            .as_array()?
            .iter()
            .map(|value| {
                let value = value.as_str()?;
                (!value.is_empty() && !value.starts_with("//") && !value.contains('\0'))
                    .then(|| PathBuf::from(value))
            })
            .collect()
    }

    fn entries(path: &Path, remaining: &mut usize) -> Option<Vec<PathBuf>> {
        let entries = match fs::read_dir(path) {
            Ok(entries) => entries,
            Err(error) if Self::missing(&error) => return Some(Vec::new()),
            Err(_) => return None,
        };
        let mut paths = Vec::new();
        for entry in entries {
            *remaining = remaining.checked_sub(1)?;
            paths.push(entry.ok()?.path());
        }
        paths.sort_unstable();
        Some(paths)
    }

    fn has_runs(project: &Path) -> Option<bool> {
        let state = project.join(".moru");
        let registry = Self::metadata(&state.join("run-registry.json"))?;
        if registry.is_some_and(|metadata| metadata.is_file()) {
            return Some(true);
        }
        Self::is_dir(&state.join("runs"))
    }

    fn is_dir(path: &Path) -> Option<bool> {
        Some(Self::metadata(path)?.is_some_and(|metadata| metadata.is_dir()))
    }

    fn metadata(path: &Path) -> Option<Option<fs::Metadata>> {
        match fs::metadata(path) {
            Ok(metadata) => Some(Some(metadata)),
            Err(error) if Self::missing(&error) => Some(None),
            Err(_) => None,
        }
    }

    fn missing(error: &std::io::Error) -> bool {
        matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR))
    }
}
