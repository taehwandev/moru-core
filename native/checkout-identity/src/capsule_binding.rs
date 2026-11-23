//! owner: immutable capsule and preflight evidence fingerprint projection.
//! allowed imports: Python-compatible escaping, serde JSON and SHA-256.
//! forbidden imports: filesystem, gate decisions, writes and providers.
//! callers/tests: completion probe and native capsule binding parity fixtures.
//! verification: original Python digests and unsupported numeric fallback.
use crate::python_text::PythonText;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

pub(crate) struct CapsuleBinding;

impl CapsuleBinding {
    pub(crate) fn fingerprint(request: &Value) -> Option<Value> {
        let source = request.get("record")?.as_object()?;
        let extra_fields: &[&str] = match request.get("kind")?.as_str()? {
            "capsule" if source.get("phase")?.as_str()? == "ready" => {
                &["phase", "preflight_evidence", "reuse_policy"]
            }
            "preflight"
                if matches!(source.get("schema_version")?, Value::Bool(true))
                    || source.get("schema_version")?.as_u64() == Some(1) =>
            {
                &[]
            }
            _ => return None,
        };
        let mut fields = Map::new();
        for key in [
            "schema_version",
            "route_fingerprint",
            "request_fingerprint",
            "required_docs",
        ]
        .into_iter()
        .chain(extra_fields.iter().copied())
        {
            let value = source.get(key)?;
            if !Self::lossless(value) {
                return None;
            }
            fields.insert(key.into(), value.clone());
        }
        let mut ordered = Value::Object(fields);
        ordered.sort_all_objects();
        let encoded = PythonText::escape_json_unicode(&serde_json::to_string(&ordered).ok()?);
        Some(json!({"sha256": format!("{:x}", Sha256::digest(encoded.as_bytes()))}))
    }

    fn lossless(value: &Value) -> bool {
        match value {
            // serde_json can represent a large integer as a float. Both that
            // case and float formatting belong to the reference implementation.
            Value::Number(number) => number.is_i64() || number.is_u64(),
            Value::Array(items) => items.iter().all(Self::lossless),
            Value::Object(items) => items.values().all(Self::lossless),
            _ => true,
        }
    }
}
