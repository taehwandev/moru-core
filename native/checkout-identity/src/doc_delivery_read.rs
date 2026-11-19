//! owner: bounded required-document and delivery manifest reads;
//! allowed imports: guarded regular-file access, newline normalization and std;
//! forbidden imports: evidence selection, writes, providers and delivery policy;
//! callers/tests: doc-transcript probe and native required-doc parity fixtures;
//! verification: UTF-8, newline normalization, omissions and unsupported paths.
use super::DocTranscript;
use crate::text::Text;
use serde_json::{Map, Value};
use std::{
    collections::HashSet,
    fs,
    io::{ErrorKind, Read},
    path::{Component, Path, PathBuf},
};

const MAX_BYTES: u64 = 128 * 1024;

impl DocTranscript {
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
}
