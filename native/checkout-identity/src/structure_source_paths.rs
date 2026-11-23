//! owner: batch eligibility of ordinary source paths for structural review.
//! allowed imports: read-only filesystem metadata and JSON.
//! forbidden imports: state writes, Git execution and vendor exclusion policy.
//! callers/tests: structural review and preview via private completion probe.
//! verification: configured source exclusions and per-path fallback.
use super::structure_net_deletions::StructureNetDeletions;
use serde_json::{json, Value};
use std::{fs, io::ErrorKind, path::Path};

pub(super) struct StructureSourcePaths;

impl StructureSourcePaths {
    pub(super) fn filter(payload: &Value) -> Option<Value> {
        let project = Path::new(payload.get("project")?.as_str()?);
        if !project.is_absolute() || project.canonicalize().ok()? != project || !project.is_dir() {
            return None;
        }
        let policy = payload.get("policy")?;
        let extensions = Self::strings(policy, "extensions")?;
        let skipped = Self::strings(policy, "skipped")?;
        let generated = Self::strings(policy, "generated")?;
        let config_names = Self::strings(policy, "config_names")?;
        let config_suffixes = Self::strings(policy, "config_suffixes")?;
        let paths = payload.get("paths")?.as_array()?;
        if paths.len() > 4096 {
            return None;
        }
        let selected = paths
            .iter()
            .map(|entry| {
                let (raw, suffix) = (entry.get("path")?.as_str()?, entry.get("suffix")?.as_str()?);
                if !extensions.contains(&suffix) {
                    return Some(false);
                }
                if !raw.is_ascii() || raw.starts_with('/') || raw.contains('\0') {
                    return None;
                }
                let parts: Vec<_> = raw.split('/').collect();
                if parts.iter().any(|part| matches!(*part, "." | ".." | "")) {
                    return None;
                }
                if parts.iter().any(|part| {
                    skipped.contains(part)
                        || generated.iter().any(|rule| part.eq_ignore_ascii_case(rule))
                }) {
                    return Some(false);
                }
                let name = parts.last()?.to_ascii_lowercase();
                let parent = parts.iter().rev().nth(1).copied();
                if config_names.contains(&name.as_str())
                    || config_suffixes.iter().any(|rule| name.ends_with(*rule))
                    || (name.ends_with(".dart") && parent == Some("pigeons"))
                {
                    return Some(false);
                }
                if parts
                    .iter()
                    .any(|part| part.eq_ignore_ascii_case("third_party"))
                {
                    return None;
                }
                match fs::metadata(project.join(raw)) {
                    Ok(metadata) => Some(metadata.is_file()),
                    Err(error) if error.kind() == ErrorKind::NotFound => Some(false),
                    Err(_) => None,
                }
            })
            .collect::<Vec<_>>();
        let mut result = json!({"selected": selected});
        if let Some(counts) = payload.get("net_deletions") {
            result["net_deletions"] = StructureNetDeletions::findings(counts)?;
        }
        Some(result)
    }

    fn strings<'a>(policy: &'a Value, key: &str) -> Option<Vec<&'a str>> {
        policy
            .get(key)?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect()
    }
}
