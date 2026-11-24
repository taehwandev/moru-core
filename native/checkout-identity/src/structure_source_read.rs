//! owner: bounded working-tree and snapshot source reads for structural review.
//! allowed imports: read-only filesystem access, UTF-8 and JSON.
//! forbidden imports: writes, Git execution and review policy.
//! callers/tests: structural review through the private completion protocol.
//! verification: compare with Python UTF-8 universal newlines and splitlines.
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::{
    fs::{self, File},
    io::Read,
    path::{Component, Path},
};

pub(super) struct StructureSourceRead;

impl StructureSourceRead {
    pub(super) fn batch(payload: &Value) -> Option<Value> {
        let source = Path::new(payload.get("source")?.as_str()?);
        if !source.is_absolute() || source.canonicalize().ok()? != source || !source.is_dir() {
            return None;
        }
        let paths = payload.get("paths")?.as_array()?;
        if paths.len() > 256 {
            return None;
        }
        // Leave room for worst-case JSON control-character escaping.
        let mut remaining = 128 * 1024;
        let rows: Vec<_> = paths
            .iter()
            .map(|path| Self::read(source, path.as_str()?, &mut remaining))
            .collect();
        Some(json!({ "rows": rows }))
    }

    fn read(source: &Path, name: &str, remaining: &mut u64) -> Option<Value> {
        let relative = Path::new(name);
        if name.is_empty()
            || name.contains('\0')
            || !relative
                .components()
                .all(|part| matches!(part, Component::Normal(_)))
        {
            return None;
        }
        let path = source.join(relative);
        let metadata = fs::metadata(&path).ok()?;
        if !metadata.is_file() || metadata.len() > *remaining {
            return None;
        }
        let mut bytes = Vec::new();
        let result = File::open(path)
            .ok()?
            .take(*remaining + 1)
            .read_to_end(&mut bytes);
        let size = bytes.len() as u64;
        let budget = *remaining;
        *remaining = remaining.saturating_sub(size);
        if result.is_err() || size > budget {
            return None;
        }
        Some(match std::str::from_utf8(&bytes) {
            Ok(text) => json!(PythonText::splitlines(text)),
            Err(_) => Value::Bool(false),
        })
    }
}
