//! owner: immutable capsule and preflight evidence fingerprint projection.
//! allowed imports: Python-compatible escaping, serde JSON and SHA-256.
//! forbidden imports: filesystem, gate decisions, writes and providers.
//! callers/tests: completion probe and native capsule binding parity fixtures.
//! verification: original Python digests and unsupported numeric fallback.
use super::{capsule_json_integers, capsule_shape::PREFLIGHT_VERSION};
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
                    || source.get("schema_version")?.as_u64() == Some(PREFLIGHT_VERSION) =>
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
            if !capsule_json_integers(value) {
                return None;
            }
            fields.insert(key.into(), value.clone());
        }
        let mut ordered = Value::Object(fields);
        ordered.sort_all_objects();
        let encoded = PythonText::escape_json_unicode(&serde_json::to_string(&ordered).ok()?);
        Some(json!({"sha256": format!("{:x}", Sha256::digest(encoded.as_bytes()))}))
    }
}
