//! owner: bounded required-document and manifest reads, registry file discovery;
//! allowed imports: guarded regular-file access, newline normalization, SHA-256 and std;
//! forbidden imports: evidence selection, writes, providers and delivery policy;
//! callers/tests: doc-transcript probe and native required-doc parity fixtures;
//! verification: UTF-8, newline normalization, raw hashes and contained regular files.
use super::DocTranscript;
use crate::text::Text;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs,
    io::{ErrorKind, Read},
    path::{Component, Path, PathBuf},
};

const MAX_BYTES: u64 = 128 * 1024;
const MAX_HASH_BYTES: u64 = 4 * 1024 * 1024;
const MAX_HASH_DOCS: usize = 256;

impl DocTranscript {
    pub(crate) fn nearest_registry_project(path: &Path) -> Option<Value> {
        let text = path.to_str()?;
        if !path.is_absolute()
            || text.starts_with("//")
            || text.len() > 4096
            || path.components().any(|part| part == Component::ParentDir)
        {
            return None;
        }
        for (depth, project) in path.ancestors().enumerate() {
            if depth == 128 {
                return None;
            }
            match fs::metadata(project.join(".moru/run-registry.json")) {
                Ok(metadata) if metadata.is_file() => {
                    return Some(serde_json::json!([project.to_str()?]));
                }
                Ok(_) => {}
                Err(error)
                    if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) => {}
                Err(_) => return None,
            }
        }
        Some(serde_json::json!([]))
    }

    pub(crate) fn read_delivery_manifest(path: &Path) -> Option<Value> {
        if path.file_name()?.to_str()? != "preflight.json" {
            return None;
        }
        let metadata = fs::metadata(path).ok()?;
        if !metadata.is_file() || metadata.len() > MAX_BYTES {
            return None;
        }
        let file = Self::open(path, &metadata)?.ok()?;
        let mut bytes = Vec::new();
        file.take(MAX_BYTES + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > MAX_BYTES {
            return None;
        }
        let manifest: Value = serde_json::from_slice(&bytes).ok()?;
        let rules = manifest.get("rules")?.as_str()?;
        let route = manifest.get("route")?.as_object()?;
        let required = match route.get("required_docs") {
            None | Some(Value::Null) => &[][..],
            Some(Value::Array(items)) => items.as_slice(),
            _ => return None,
        };
        let mut seen = HashSet::new();
        let mut docs = Vec::new();
        for item in required {
            let name = item.as_str()?;
            if seen.insert(name) {
                docs.push(name);
            }
        }
        Some(serde_json::json!([rules, docs]))
    }

    pub(crate) fn read_documents(rules: &Path, docs: &[&str]) -> Option<Value> {
        let root = rules.canonicalize().ok()?;
        let mut remaining = MAX_BYTES;
        let mut texts = Map::new();
        for &name in docs {
            let relative = Path::new(name);
            if relative.is_absolute()
                || relative
                    .components()
                    .any(|part| part == Component::ParentDir)
            {
                return None;
            }
            let normalized: PathBuf = relative.components().collect();
            let path = root.join(normalized);
            let metadata = match fs::symlink_metadata(&path) {
                Ok(metadata) => metadata,
                Err(error)
                    if matches!(error.kind(), ErrorKind::NotFound | ErrorKind::NotADirectory) =>
                {
                    continue
                }
                Err(_) => return None,
            };
            if metadata.is_dir() {
                continue;
            }
            if !metadata.is_file()
                || metadata.len() > remaining
                || !path.canonicalize().ok()?.starts_with(&root)
            {
                return None;
            }
            let file = Self::open(&path, &metadata)?.ok()?;
            let mut bytes = Vec::new();
            file.take(remaining + 1).read_to_end(&mut bytes).ok()?;
            remaining = remaining.checked_sub(bytes.len() as u64)?;
            let text = Text::universal_newlines(std::str::from_utf8(&bytes).ok()?);
            texts.insert(name.into(), Value::String(text));
        }
        Some(Value::Object(texts))
    }

    pub(crate) fn hash_documents(rules: &Path, docs: &[&str]) -> Option<Value> {
        if docs.is_empty() {
            return Some(json!([]));
        }
        if docs.len() > MAX_HASH_DOCS || !rules.is_absolute() {
            return None;
        }
        let root = rules.canonicalize().ok()?;
        if root.as_os_str() != rules.as_os_str() {
            return None;
        }
        let mut remaining = MAX_HASH_BYTES;
        let mut records = Vec::with_capacity(docs.len());
        let mut buffer = [0; 32 * 1024];
        for &name in docs {
            let relative = Path::new(name);
            if relative.is_absolute()
                || relative
                    .components()
                    .any(|part| part == Component::ParentDir)
            {
                return None;
            }
            let normalized: PathBuf = relative.components().collect();
            let path = root.join(normalized).canonicalize().ok()?;
            if !path.starts_with(&root) {
                return None;
            }
            let metadata = fs::metadata(&path).ok()?;
            if !metadata.is_file() || metadata.len() > remaining {
                return None;
            }
            let mut reader = Self::open_scoped(&path, &metadata, Some(&root))?
                .ok()?
                .take(remaining + 1);
            let mut hasher = Sha256::new();
            let mut size = 0_u64;
            loop {
                let read = reader.read(&mut buffer).ok()?;
                if read == 0 {
                    break;
                }
                size += read as u64;
                hasher.update(&buffer[..read]);
            }
            remaining = remaining.checked_sub(size)?;
            records.push(json!({
                "path": name,
                "size_bytes": size,
                "sha256": format!("{:x}", hasher.finalize()),
            }));
        }
        Some(Value::Array(records))
    }
}
