//! owner: bounded required-document file reads;
//! allowed imports: guarded regular-file access, newline normalization and std;
//! forbidden imports: evidence selection, writes, providers and delivery policy;
//! callers/tests: doc-transcript probe and native required-doc parity fixtures;
//! verification: UTF-8, newline normalization, omissions and unsupported paths.
use super::DocTranscript;
use crate::text::Text;
use serde_json::{Map, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    path::{Component, Path, PathBuf},
};

const MAX_BYTES: u64 = 128 * 1024;

impl DocTranscript {
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
