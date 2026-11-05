//! Owner: versioned requirement mappings and read-only coverage checks.
//! Allowed: std, serde_json, sha2, existing libc. Forbidden: execution, waivers, writes/authority.
//! Callers/tests: completion_process; native completion and finish tests.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    os::unix::fs::OpenOptionsExt,
    path::Path,
};

pub(crate) struct Requirements;

impl Requirements {
    pub(crate) fn validate(value: &Value) -> Option<Value> {
        let current = value.get("current")?;
        let mut failures = Self::schema(current);
        if let Some(previous) = value.get("previous").filter(|v| !v.is_null()) {
            failures.extend(Self::schema(previous));
            if failures.is_empty() {
                let before = previous["revision"].as_u64()?;
                let after = current["revision"].as_u64()?;
                if after < before || (current["items"] != previous["items"] && after <= before) {
                    failures.push("requirements_revision_must_advance".into());
                }
                let ids: BTreeSet<_> = current["items"]
                    .as_array()?
                    .iter()
                    .map(|v| v["id"].as_str().unwrap())
                    .collect();
                if previous["items"]
                    .as_array()?
                    .iter()
                    .any(|v| !ids.contains(v["id"].as_str().unwrap()))
                {
                    failures.push("requirements_cannot_disappear".into());
                }
            }
        }
        Some(json!({"failures":failures}))
    }

    pub(crate) fn coverage(value: &Value) -> Option<Value> {
        let current = value.get("current")?;
        let mut failures = Self::schema(current);
        if !failures.is_empty() {
            return Some(json!({"failures":failures,"observations":[]}));
        }
        let project = Path::new(value.get("project")?.as_str()?);
        if !project.is_absolute() || !project.is_dir() {
            return None;
        }
        let gates = value.get("gates")?.as_array()?;
        // The transport bounds bytes. History length is not effective gate count.
        let mut statuses = BTreeMap::new();
        for record in gates {
            statuses.insert(
                record.get("gate")?.as_str()?,
                record.get("status")?.as_str()?,
            );
        }
        let allowed: BTreeSet<_> = value
            .get("allowed_gates")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<_>>()?;
        let mut observations = Vec::new();
        let mut total = 0usize;
        for item in current["items"].as_array()? {
            let id = item["id"].as_str()?;
            let gate = item["gate"].as_str()?;
            if !allowed.contains(gate) || statuses.get(gate) != Some(&"SUCCESS") {
                failures.push(format!(
                    "requirement {id}: observing gate is missing or unmet"
                ));
            }
            let mut artifacts = BTreeMap::new();
            for raw in item["artifacts"].as_array()? {
                let relative = raw.as_str()?;
                match Self::artifact(project, relative, 32 * 1024 * 1024 - total) {
                    Ok(bytes) => {
                        total += bytes.len();
                        artifacts.insert(relative, format!("{:x}", Sha256::digest(&bytes)));
                    }
                    Err(reason) => failures.push(format!("requirement {id}: {reason}")),
                }
            }
            observations.push(json!({"id":id,"artifacts":artifacts}));
        }
        Some(json!({"failures":failures,"observations":observations}))
    }

    fn artifact(project: &Path, relative: &str, remaining: usize) -> Result<Vec<u8>, &'static str> {
        let unsafe_path = "artifact is missing or unsafe";
        let mut path = project.to_owned();
        if fs::symlink_metadata(&path)
            .map_err(|_| unsafe_path)?
            .file_type()
            .is_symlink()
        {
            return Err(unsafe_path);
        }
        for part in relative.split('/') {
            path.push(part);
            if fs::symlink_metadata(&path)
                .map_err(|_| unsafe_path)?
                .file_type()
                .is_symlink()
            {
                return Err(unsafe_path);
            }
        }
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(|_| "artifact is unreadable or unsafe")?;
        let metadata = file.metadata().map_err(|_| "artifact is unreadable")?;
        if !metadata.is_file() {
            return Err(unsafe_path);
        }
        let per_file = 16 * 1024 * 1024;
        if metadata.len() > per_file as u64 {
            return Err("artifact exceeds 16 MiB file limit");
        }
        if metadata.len() > remaining as u64 {
            return Err("artifacts exceed 32 MiB total limit");
        }
        let mut bytes = Vec::new();
        file.take(per_file.min(remaining) as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "artifact is unreadable")?;
        if bytes.len() > per_file {
            return Err("artifact exceeds 16 MiB file limit");
        }
        if bytes.len() > remaining {
            return Err("artifacts exceed 32 MiB total limit");
        }
        Ok(bytes)
    }

    fn schema(value: &Value) -> Vec<String> {
        let invalid = || vec!["invalid_requirements_contract".into()];
        let Some(map) = value.as_object() else {
            return invalid();
        };
        if map.len() != 2 || value["revision"].as_u64().filter(|n| *n > 0).is_none() {
            return invalid();
        }
        let Some(items) = value["items"].as_array() else {
            return invalid();
        };
        if items.is_empty() || items.len() > 32 {
            return invalid();
        }
        let mut ids = BTreeSet::new();
        for item in items {
            let Some(map) = item.as_object() else {
                return invalid();
            };
            if map.len() != 5
                || !["id", "outcome", "owner", "gate", "artifacts"]
                    .iter()
                    .all(|k| map.contains_key(*k))
            {
                return invalid();
            }
            let Some(id) = item["id"].as_str() else {
                return invalid();
            };
            if id.is_empty()
                || id.len() > 40
                || !id.as_bytes()[0].is_ascii_alphanumeric()
                || !id
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"_.-".contains(&b))
                || !ids.insert(id)
            {
                return invalid();
            }
            for key in ["outcome", "owner", "gate"] {
                let Some(text) = item[key].as_str() else {
                    return invalid();
                };
                if text.trim().is_empty()
                    || text.chars().count() > 280
                    || text.chars().any(char::is_control)
                {
                    return invalid();
                }
            }
            let Some(paths) = item["artifacts"].as_array() else {
                return invalid();
            };
            if paths.len() > 8 {
                return invalid();
            }
            let mut unique = BTreeSet::new();
            for path in paths {
                let Some(path) = path.as_str() else {
                    return invalid();
                };
                if path.len() > 1000
                    || path.contains('\\')
                    || path.chars().any(char::is_control)
                    || path
                        .split('/')
                        .any(|v| matches!(v, "" | "." | ".." | ".git" | ".moru"))
                    || !unique.insert(path)
                {
                    return invalid();
                }
            }
        }
        Vec::new()
    }
}
