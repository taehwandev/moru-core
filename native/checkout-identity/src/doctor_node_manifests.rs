//! owner: read-only Node manifest script discovery for doctor.
//! allowed imports: bounded local reads, existing Python JSON parser and std.
//! forbidden imports: command execution, permission policy, writes and installers.
//! callers/tests: completion probe and doctor permission count parity.
//! verification: root and immediate children, script order and reference fallback.
use crate::{
    atomic_sibling::AtomicSibling,
    python_json::{ParseOutcome, PythonJson, Value as Source},
    text::Text,
};
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::Path,
};

pub(super) struct DoctorNodeManifests;

const MAX_ENTRIES: usize = 4096;
const MAX_MANIFEST: u64 = 256 * 1024;
const MAX_TOTAL: u64 = 1024 * 1024;
const EXCLUDED_NAMES: [&str; 5] = ["node_modules", ".git", "dist", ".next", "build"];

impl DoctorNodeManifests {
    pub(super) fn inspect(payload: &Value) -> Option<Value> {
        let project = Path::new(payload.get("project")?.as_str()?);
        if !project.is_absolute() || project.canonicalize().ok()? != project {
            return None;
        }
        let mut groups = Vec::new();
        let mut remaining = MAX_TOTAL;
        if let Some(names) = Self::read(project, &mut remaining)? {
            groups.push(names);
        }
        for (index, entry) in fs::read_dir(project).ok()?.enumerate() {
            if index == MAX_ENTRIES {
                return None;
            }
            let entry = entry.ok()?;
            if EXCLUDED_NAMES.iter().any(|name| entry.file_name() == *name) {
                continue;
            }
            let kind = entry.file_type().ok()?;
            if kind.is_symlink() && entry.path().is_dir() {
                return None;
            }
            if kind.is_dir() {
                if let Some(names) = Self::read(&entry.path(), &mut remaining)? {
                    groups.push(names);
                }
            }
        }
        Some(json!({"scripts": groups}))
    }

    fn read(parent: &Path, remaining: &mut u64) -> Option<Option<Vec<String>>> {
        match fs::symlink_metadata(parent.join("package.json")) {
            Ok(metadata) if metadata.is_dir() => return Some(None),
            Ok(metadata) if metadata.is_file() => {}
            Err(error) if error.kind() == ErrorKind::NotFound => return Some(None),
            _ => return None,
        }
        let directory = AtomicSibling::open_directory(parent)?;
        let manifest = AtomicSibling::open_relative(&directory, c"package.json", libc::O_RDONLY)?;
        let metadata = manifest.metadata().ok()?;
        let limit = (*remaining).min(MAX_MANIFEST);
        if !metadata.is_file() || metadata.len() > limit {
            return None;
        }
        let mut bytes = Vec::new();
        manifest.take(limit + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > limit {
            return None;
        }
        *remaining -= bytes.len() as u64;
        let Ok(text) = std::str::from_utf8(&bytes) else {
            return Some(None);
        };
        let text = Text::universal_newlines(text);
        if text
            .as_bytes()
            .split(|byte| !byte.is_ascii_digit())
            .any(|digits| digits.len() > 640)
        {
            return None;
        }
        let object = match PythonJson::parse_outcome(&text) {
            ParseOutcome::Value(Source::Object(object)) => object,
            ParseOutcome::Invalid => return Some(None),
            _ => return None,
        };
        match object.get("scripts") {
            Some(Source::Object(scripts)) => {
                Some(Some(scripts.iter().map(|(name, _)| name.clone()).collect()))
            }
            None => Some(Some(Vec::new())),
            _ => None,
        }
    }
}
