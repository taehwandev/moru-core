//! owner: canonical route and request identity digests.
//! allowed imports: Python-compatible JSON values, serde JSON quoting and SHA-256.
//! forbidden imports: files, ledger mutation, authorization and providers.
//! callers/tests: native next and capsule preflight identity.
//! verification: route/request digest parity and local-delivery contract binding.
use crate::python_json::{Object, PythonJson as Py, Value};
use serde_json::json;
use sha2::{Digest, Sha256};

pub(crate) struct RouteIdentity;

impl RouteIdentity {
    pub(crate) fn probe(bytes: &[u8]) -> Option<serde_json::Value> {
        let payload = Py::parse(std::str::from_utf8(bytes).ok()?)?;
        let route = payload.get("route")?.as_object()?;
        let intake = payload.get("intake")?.as_object()?;
        Some(json!({
            "route_fingerprint": Self::route_hash(route)?,
            "request_fingerprint": Self::request_hash(intake)?,
        }))
    }

    fn request_hash(intake: &Object) -> Option<String> {
        let mut stable = Object::new();
        for key in ["request", "continuation_scope", "classification_evidence"] {
            let field = intake.get(key).filter(|value| Py::truthy(value));
            let text = match field {
                Some(Value::String(text)) => text.as_str(),
                Some(_) => return None,
                None => "",
            };
            stable.insert(key.into(), Value::String(text.into()));
        }
        let classified = intake.get("request_classified").is_some_and(Py::truthy);
        stable.insert("request_classified".into(), Value::Bool(classified));
        Some(Self::digest(stable))
    }

    fn digest(fields: Object) -> String {
        format!(
            "{:x}",
            Sha256::digest(Self::canonical(&Value::Object(fields)).as_bytes())
        )
    }

    pub(crate) fn route_hash(route: &Object) -> Option<String> {
        let mut stable = Object::new();
        for key in ["command", "platform"] {
            stable.insert(key.into(), route.get(key).cloned().unwrap_or(Value::Null));
        }
        for key in [
            "concerns",
            "docs",
            "required_docs",
            "reference_docs",
            "gates",
        ] {
            stable.insert(
                key.into(),
                route
                    .get(key)
                    .filter(|v| Py::truthy(v))
                    .cloned()
                    .unwrap_or_else(|| Value::Array(Vec::new())),
            );
        }
        for key in [
            "lifecycle_version",
            "project_memory_contract",
            "local_delivery_contract",
        ] {
            if let Some(value) = route.get(key) {
                stable.insert(key.into(), value.clone());
            }
        }
        if let Some(org) = route.get("organization").filter(|v| Py::truthy(v)) {
            let org = org.as_object()?;
            let mut block = Object::new();
            for key in ["id", "commit"] {
                block.insert(key.into(), org.get(key).cloned().unwrap_or(Value::Null));
            }
            let mut docs = Vec::new();
            if let Some(entries) = org.get("required_docs").filter(|v| Py::truthy(v)) {
                for item in entries.as_array()? {
                    let item = item.as_object()?;
                    docs.push(Value::Array(
                        ["path", "sha256"]
                            .iter()
                            .map(|key| item.get(key).cloned().unwrap_or(Value::Null))
                            .collect(),
                    ));
                }
            }
            block.insert("required_docs".into(), Value::Array(docs));
            stable.insert("organization".into(), Value::Object(block));
        }
        Some(Self::digest(stable))
    }
    fn canonical(value: &Value) -> String {
        match value {
            Value::Null => "null".into(),
            Value::Bool(v) => v.to_string(),
            Value::String(s) => serde_json::to_string(s).unwrap(),
            Value::Number(n) => match n.text().as_str() {
                "nan" => "NaN".into(),
                "inf" => "Infinity".into(),
                "-inf" => "-Infinity".into(),
                _ => n.text(),
            },
            Value::Array(items) => format!(
                "[{}]",
                items
                    .iter()
                    .map(Self::canonical)
                    .collect::<Vec<_>>()
                    .join(",")
            ),
            Value::Object(map) => {
                let mut entries = map.iter().collect::<Vec<_>>();
                entries.sort_by(|a, b| a.0.cmp(b.0));
                format!(
                    "{{{}}}",
                    entries
                        .iter()
                        .map(|(k, v)| format!(
                            "{}:{}",
                            serde_json::to_string(k).unwrap(),
                            Self::canonical(v)
                        ))
                        .collect::<Vec<_>>()
                        .join(",")
                )
            }
        }
    }
}
