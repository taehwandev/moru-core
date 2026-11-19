//! Owner: staged_v1 Git listing identity. Allowed: pure text, JSON and SHA-256.
//! Forbidden: Git commands, repository reads/writes, or publication decisions.
//! Caller: completion probe; verified against the Python capture and observer.

use crate::python_text::PythonText;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub(crate) struct LocalDeliveryIdentity;

impl LocalDeliveryIdentity {
    pub(crate) fn capture(payload: &Value) -> Option<Value> {
        let staged = Self::digest(payload.get("index")?.as_str()?, true)?;
        let base = Self::digest(payload.get("base")?.as_str()?, false)?;
        Some(json!({"staged": staged, "base": base}))
    }

    fn digest(listing: &str, index: bool) -> Option<String> {
        let mut entries = Vec::new();
        for entry in listing.split('\0').filter(|entry| !entry.is_empty()) {
            let (metadata, path) = entry.split_once('\t')?;
            let mut fields = metadata
                .split(PythonText::whitespace)
                .filter(|field| !field.is_empty());
            let (mode, second, third) = (fields.next()?, fields.next()?, fields.next()?);
            if fields.next().is_some() || (index && third != "0") {
                return None;
            }
            entries.push((path, mode, if index { second } else { third }));
        }
        entries.sort_unstable();
        let mut hash = Sha256::new();
        hash.update(b"[");
        for (ordinal, (path, mode, oid)) in entries.into_iter().enumerate() {
            if ordinal > 0 {
                hash.update(b",");
            }
            hash.update(b"[");
            hash.update(PythonText::json_ascii(path)?);
            hash.update(b",");
            hash.update(PythonText::json_ascii(mode)?);
            hash.update(b",");
            hash.update(PythonText::json_ascii(oid)?);
            hash.update(b"]");
        }
        hash.update(b"]");
        Some(format!("{:x}", hash.finalize()))
    }
}
