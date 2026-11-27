//! Owner: immediate workspace project discovery for status trends.
//! Allowed: read-only filesystem metadata, DiscoveryFs and JSON.
//! Forbidden: recursive scans, state reads, Git, and writes.
//! Callers/tests: completion_process and status trend discovery parity.
use crate::discovery_fs::DiscoveryFs;
use serde_json::{json, Value};
use std::{fs, path::Path};

const MAX_ENTRIES: usize = 4096;
const MAX_RESULT_BYTES: usize = 512 * 1024;

pub(super) fn discover(request: &Value) -> Option<Value> {
    let root = request.get("root")?.as_str()?;
    if !root.starts_with('/') || root.starts_with("//") || root.contains('\0') {
        return None;
    }
    let root = Path::new(root);
    if !metadata(root)?.is_some_and(|entry| entry.is_dir()) {
        return Some(json!({"projects": []}));
    }

    let mut children = Vec::new();
    for entry in fs::read_dir(root).ok()? {
        if children.len() == MAX_ENTRIES {
            return None;
        }
        children.push(entry.ok()?.file_name().into_string().ok()?);
    }
    children.sort_unstable();

    let mut projects = Vec::new();
    let mut bytes = 0usize;
    for name in children {
        let child = root.join(name);
        if !metadata(&child)?.is_some_and(|entry| entry.is_dir()) {
            continue;
        }
        let state = child.join(".moru");
        if !metadata(&state.join("runs"))?.is_some_and(|entry| entry.is_dir())
            && !metadata(&state.join("run-registry.json"))?.is_some_and(|entry| entry.is_file())
        {
            continue;
        }
        // Resolve after sorting, preserving distinct aliases of one checkout.
        let resolved = DiscoveryFs::resolve(&child)?;
        let path = resolved.to_str()?;
        bytes = bytes.checked_add(serde_json::to_vec(path).ok()?.len() + 1)?;
        if bytes > MAX_RESULT_BYTES {
            return None;
        }
        projects.push(path.to_owned());
    }
    Some(json!({"projects": projects}))
}

fn metadata(path: &Path) -> Option<Option<fs::Metadata>> {
    match fs::metadata(path) {
        Ok(metadata) => Some(Some(metadata)),
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP)
            ) =>
        {
            Some(None)
        }
        Err(_) => None,
    }
}
