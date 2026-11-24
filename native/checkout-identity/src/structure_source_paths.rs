//! owner: batch eligibility of ordinary source paths for structural review.
//! allowed imports: read-only filesystem metadata, vendor README, bounded Git attributes and JSON.
//! forbidden imports: state writes, arbitrary Git execution and review decisions.
//! callers/tests: structural review and preview via private completion probe.
//! verification: configured source exclusions and per-path fallback.
use super::structure_net_deletions::StructureNetDeletions;
use crate::read_process::status::capture_status;
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::Path,
    process::Command,
    time::Duration,
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
        let query = payload.get("read_git_attributes").and_then(Value::as_bool) == Some(true);
        let attributes = match (query, payload.get("git_attributes")) {
            (true, None) => Self::generated_flags(&Self::git_attributes(project, paths)?, paths)?,
            (false, Some(records)) => Self::generated_flags(records.as_str()?, paths)?,
            (false, None) => vec![false; paths.len()],
            (true, Some(_)) => return None,
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
        if query {
            result["git_attributes_read"] = Value::Bool(true);
        }
        if let Some(counts) = payload.get("net_deletions") {
            result["net_deletions"] = StructureNetDeletions::findings(counts)?;
        }
        Some(result)
    }

    fn git_attributes(project: &Path, paths: &[Value]) -> Option<String> {
        let mut input = Vec::new();
        for entry in paths {
            let path = entry.get("path")?.as_str()?;
            if path.is_empty() || path.contains('\0') || input.len() + path.len() + 1 > 128 * 1024 {
                return None;
            }
            input.extend_from_slice(path.as_bytes());
            input.push(0);
        }
        if input.is_empty() {
            return Some(String::new());
        }
        let (output, _, status) = capture_status(
            Command::new("git")
                .arg("-C")
                .arg(project)
                .args(["check-attr", "-z", "--stdin", "linguist-generated"])
                .env("GIT_OPTIONAL_LOCKS", "0")
                .env("GIT_TERMINAL_PROMPT", "0")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_ALLOW_PROTOCOL", ""),
            Duration::from_secs(2),
            Some(256 * 1024),
            Some(input),
        )
        .ok()??;
        if !status.success() {
            return None;
        }
        String::from_utf8(output).ok()
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
