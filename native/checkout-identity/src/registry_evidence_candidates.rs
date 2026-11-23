//! owner: canonical runtime evidence discovery from frozen registry bindings;
//! allowed imports: filesystem metadata, SHA-256 and JSON;
//! forbidden imports: registry mutation, claim selection, worker and session policy;
//! callers/tests: private registry probe and native registry/session parity;
//! verification: complete exact keys, readable directories, checkout limits and order.
use super::RegistryRead;
use crate::pending_publication_receipt::PendingPublicationReceipt;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs, io::ErrorKind, path::Path};

impl RegistryRead {
    pub(super) fn evidence_candidates(payload: &Value) -> Option<Value> {
        if payload.as_object()?.len() != 2 {
            return None;
        }
        let project = Path::new(payload.get("project")?.as_str()?);
        let claims = payload.get("claims")?.as_array()?;
        if claims.len() > 256
            || !project.is_absolute()
            || project.canonicalize().ok()?.as_os_str() != project.as_os_str()
        {
            return None;
        }
        let state = project.join(".moru");
        let runs = state.join("runs");
        readable_directory(&state)?;
        run_directory(&runs)?;
        let mut ranked = Vec::with_capacity(claims.len());
        for (index, claim) in claims.iter().enumerate() {
            let [key, id, basename] = claim.as_array()?.as_slice() else {
                return None;
            };
            let id = id.as_str()?;
            let basename = basename.as_str()?;
            if !PendingPublicationReceipt::is_id(id)
                || basename.is_empty()
                || matches!(basename, "." | "..")
                || basename.contains('/')
            {
                return None;
            }
            let directory = runs.join(id);
            run_directory(&directory)?;
            let candidate = directory.join(basename);
            if !fs::symlink_metadata(&candidate).ok()?.is_file()
                || candidate.canonicalize().ok()?.as_os_str() != candidate.as_os_str()
            {
                return None;
            }
            let relative = candidate.strip_prefix(project).ok()?.to_str()?;
            if format!("{:x}", Sha256::digest(relative.as_bytes())) != key.as_str()? {
                return None;
            }
            ranked.push((candidate, index));
        }
        ranked.sort_unstable();
        Some(json!(ranked
            .into_iter()
            .map(|(_, index)| index)
            .collect::<Vec<_>>()))
    }
}

fn readable_directory(path: &Path) -> Option<()> {
    if !fs::symlink_metadata(path).ok()?.is_dir() {
        return None;
    }
    // Merely being able to stat a file is not enough if the walk could not
    // enumerate its directory.
    fs::read_dir(path).ok()?;
    Some(())
}

fn run_directory(path: &Path) -> Option<()> {
    // A dangling .git symlink is a checkout marker to the Python walk too.
    match fs::symlink_metadata(path.join(".git")) {
        Err(error) if error.kind() == ErrorKind::NotFound => readable_directory(path),
        _ => None,
    }
}
