//! owner: read and validate local research decision input in caller order.
//! allowed imports: guarded local file opens, bounded JSON, Python whitespace and identity sets.
//! forbidden imports: credentials, network, cache access and filesystem writes.
//! callers/tests: DecisionCachePlan; test_microsoft_decision.
//! verification: exact first-error and Python rollback on unsupported transport.
use crate::{atomic_sibling::AtomicSibling, python_text::PythonText};
use serde_json::Value;
use std::{collections::HashSet, ffi::CString, io::Read, os::unix::ffi::OsStrExt, path::Path};

const MAX_INPUT_BYTES: usize = 1024 * 1024;
const SOURCE_FIELDS: [&str; 6] = ["id", "url", "title", "text", "required", "published_at"];

pub(crate) struct DecisionInput;

impl DecisionInput {
    pub(crate) fn read(path: &Path) -> Option<Value> {
        let directory = AtomicSibling::open_directory(path.parent()?)?;
        let name = CString::new(path.file_name()?.as_bytes()).ok()?;
        let file = AtomicSibling::open_relative(&directory, &name, libc::O_RDONLY)?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut bytes = Vec::new();
        file.take((MAX_INPUT_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .ok()?;
        if bytes.len() > MAX_INPUT_BYTES {
            return None;
        }
        serde_json::from_slice(&bytes).ok()
    }

    pub(crate) fn validate(payload: &Value) -> Result<(), &'static str> {
        let query = payload
            .get("query")
            .and_then(Value::as_str)
            .ok_or("Input needs a query and sources")?;
        let sources = payload
            .get("sources")
            .and_then(Value::as_array)
            .filter(|_| !blank(query))
            .ok_or("Input needs a nonempty query and a sources array")?;
        let mut seen = HashSet::new();
        for source in sources {
            let source = source.as_object().ok_or("Each source must be an object")?;
            for field in ["id", "url", "title", "text"] {
                if source.get(field).and_then(Value::as_str).is_none_or(blank) {
                    return Err("Each source needs id, url, title, and text");
                }
            }
            let id = source["id"]
                .as_str()
                .ok_or("Each source needs id, url, title, and text")?;
            if !seen.insert(id) {
                return Err("Source ids must be unique");
            }
            if source
                .get("required")
                .is_some_and(|value| !value.is_boolean())
            {
                return Err("required must be a boolean");
            }
            if source
                .get("published_at")
                .is_some_and(|value| !value.is_string())
            {
                return Err("published_at must be a string");
            }
        }
        Ok(())
    }

    pub(crate) fn project(payload: &Value) -> Option<Value> {
        let sources: Option<Vec<Value>> = payload
            .get("sources")?
            .as_array()?
            .iter()
            .map(|source| {
                let source = source.as_object()?;
                Some(Value::Object(
                    SOURCE_FIELDS
                        .into_iter()
                        .filter_map(|field| {
                            source.get(field).map(|value| (field.into(), value.clone()))
                        })
                        .collect(),
                ))
            })
            .collect();
        Some(serde_json::json!({"query": payload.get("query")?, "sources": sources?}))
    }
}

fn blank(text: &str) -> bool {
    text.trim_matches(PythonText::whitespace).is_empty()
}
