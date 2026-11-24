//! owner: batch eligibility of ordinary source paths for structural review.
//! allowed imports: read-only filesystem metadata and vendor README, Git attribute records and JSON.
//! forbidden imports: state writes and Git execution.
//! callers/tests: structural review and preview via private completion probe.
//! verification: configured source exclusions and per-path fallback.
use super::structure_net_deletions::StructureNetDeletions;
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::Path,
};

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
        let attributes = match payload.get("git_attributes") {
            Some(records) => Self::generated_flags(records.as_str()?, paths)?,
            None => vec![false; paths.len()],
        };
        let selected = paths
            .iter()
            .zip(attributes)
            .map(|(entry, git_generated)| {
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
                if Self::pinned_vendor(project, &parts)? || git_generated {
                    return Some(false);
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

    fn pinned_vendor(project: &Path, parts: &[&str]) -> Option<bool> {
        const MAX_README_BYTES: u64 = 128 * 1024;
        let Some(package) = parts
            .iter()
            .position(|part| part.eq_ignore_ascii_case("third_party"))
            .and_then(|boundary| parts.get(..boundary + 2))
        else {
            return Some(false);
        };
        let package = project.join(package.join("/"));
        let readme = package.join("README.md");
        for file in [&readme, &package.join("LICENSE")] {
            match fs::metadata(file) {
                Ok(metadata) if metadata.is_file() => {}
                Ok(_) => return Some(false),
                Err(error)
                    if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) =>
                {
                    return Some(false);
                }
                Err(_) => return None,
            }
        }
        let mut bytes = Vec::new();
        fs::File::open(readme)
            .ok()?
            .take(MAX_README_BYTES + 1)
            .read_to_end(&mut bytes)
            .ok()?;
        if bytes.len() as u64 > MAX_README_BYTES {
            return None;
        }
        let provenance = std::str::from_utf8(&bytes).ok()?.to_lowercase();
        Some(
            ["upstream", "commit", "sha-256", "license"]
                .iter()
                .all(|marker| provenance.contains(marker)),
        )
    }

    fn generated_flags(records: &str, paths: &[Value]) -> Option<Vec<bool>> {
        let mut fields = records.strip_suffix('\0')?.split('\0');
        let mut flags = Vec::with_capacity(paths.len());
        for entry in paths {
            if fields.next()? != entry.get("path")?.as_str()?
                || fields.next()? != "linguist-generated"
            {
                return None;
            }
            let value = fields.next()?;
            // The single-path reader splits on the last colon and uses Python str.strip().
            let value = value
                .rsplit(':')
                .next()?
                .trim_matches(|ch: char| ch.is_whitespace() || matches!(ch, '\u{1c}'..='\u{1f}'));
            flags.push(matches!(value, "set" | "true"));
        }
        fields.next().is_none().then_some(flags)
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
