//! Owner: read-only discovery orchestration over registry and filesystem owners.
//! Allowed: std, serde_json, discovery_fs/candidates/registry/groups.
//! Forbidden: writes, launch/effect policy and cross-call caches.
//! Callers/tests: discovery_process; native discovery/registry tests.
use crate::{
    discovery_candidates::Candidates, discovery_fs::DiscoveryFs as Fs,
    discovery_groups::WorkspaceGroups, discovery_registry::Registry,
};
use serde_json::Value;
use std::{
    env,
    path::{Path, PathBuf},
};

pub(crate) struct DiscoverySearch;

impl DiscoverySearch {
    pub(crate) fn find(
        request: &str,
        cwd: &Path,
        registry: Option<&Path>,
        roots: &[PathBuf],
        depth: usize,
        defaults: bool,
        snapshot: Option<&Value>,
    ) -> Option<Value> {
        // Explicit request-path grammar remains Python-owned.
        if request.len() > 16384 || request.contains(['/', '\\', '~', '$', '.', '\'', '"', '`']) {
            return None;
        }
        let request = Fs::lower(request)?;
        let registered = Registry::load(registry, snapshot)?;
        let mut scans = Registry::roots(&registered)?;
        if let Some(paths) = env::var_os("MORU_PROJECT_SEARCH_ROOTS") {
            for path in env::split_paths(&paths).filter(|p| !p.as_os_str().is_empty()) {
                scans.push(Registry::path(path.to_str()?)?);
            }
        }
        scans.extend_from_slice(roots);
        if defaults {
            let home = PathBuf::from(env::var_os("HOME")?);
            scans.extend(
                [
                    "Documents",
                    "Developer",
                    "GitHub",
                    "git",
                    "Projects",
                    "Downloads",
                ]
                .map(|p| home.join(p)),
            );
        }
        let cwd = Fs::resolve(&Fs::expand(cwd)?)?;
        let mut candidates = Candidates::new();
        Registry::add_projects(&registered, &request, &mut candidates)?;
        collect(&request, &cwd, &registered, scans, depth, &mut candidates)?;
        candidates.finish(&request)
    }
}

fn collect(
    request: &str,
    cwd: &Path,
    registered: &Value,
    scans: Vec<PathBuf>,
    depth: usize,
    candidates: &mut Candidates,
) -> Option<()> {
    if let Some(root) = Fs::root(cwd)? {
        if !Candidates::has_slug(request)
            || Candidates::matches(
                root.file_name().and_then(|s| s.to_str()).unwrap_or(""),
                request,
                false,
            )?
        {
            let (files, markers) = Fs::facts(&root)?;
            candidates.add(
                root,
                files,
                markers,
                65,
                "current working directory is inside a project",
                "cwd",
                &[],
            )?;
        }
    }
    WorkspaceGroups::add(registered, request, candidates)?;
    let mut seen = Vec::new();
    for root in scans {
        if seen.contains(&root) {
            continue;
        }
        seen.push(root.clone());
        if !Fs::exists(&root)? || !root.is_dir() {
            continue;
        }
        for (path, files, markers) in Fs::scan(&root, depth)? {
            let matched = Candidates::matches(
                path.file_name().and_then(|s| s.to_str()).unwrap_or(""),
                request,
                false,
            )?;
            candidates.add(
                Fs::resolve(&path)?,
                files,
                markers,
                if matched { 100 } else { 35 },
                if matched {
                    "project name matched request under configured search root"
                } else {
                    "project marker found under configured search root"
                },
                "search_root",
                &[],
            )?;
        }
    }
    Some(())
}
