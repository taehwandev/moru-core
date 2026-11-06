//! owner: LedgerBinding; allowed imports: PythonJson, sha2, std, serde_json quoting;
//! forbidden imports: state mutation, subprocess; callers/tests: NextLedger;
//! verification: canonical route/preflight identity fixtures.
use crate::python_json::{Object, PythonJson as Py, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};
pub(super) struct LedgerBinding;
impl LedgerBinding {
    pub fn matches(
        ledger: &Object,
        evidence: &Path,
        route: &Object,
        bytes: &[u8],
        schema: u64,
    ) -> Option<bool> {
        if !Self::equals(ledger.get("schema_version"), schema) {
            return Some(false);
        }
        let recorded = ledger
            .get("preflight_evidence")
            .map(Py::string)
            .unwrap_or_else(|| "None".into());
        let path = if recorded == "~" || recorded.starts_with("~/") {
            let home = std::env::var_os("HOME")?;
            PathBuf::from(home).join(recorded.strip_prefix("~/").unwrap_or(""))
        } else if recorded.starts_with('~') {
            return None;
        } else {
            PathBuf::from(recorded)
        };
        match path.canonicalize() {
            Ok(path) if path == evidence => {}
            Ok(_) => return Some(false),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return None,
            Err(e) if e.kind() == std::io::ErrorKind::InvalidInput => return Some(false),
            Err(_) => return None,
        }
        let current = fs::read(evidence).ok()?;
        if current != bytes {
            return None;
        }
        let hash = format!("{:x}", Sha256::digest(&current));
        if ledger
            .get("preflight_evidence_sha256")
            .and_then(Value::as_str)
            != Some(hash.as_str())
        {
            return Some(false);
        }
        let fingerprint = Self::route_hash(route)?;
        Some(ledger.get("route_fingerprint").and_then(Value::as_str) == Some(fingerprint.as_str()))
    }
    pub fn equals(value: Option<&Value>, expected: u64) -> bool {
        match value {
            Some(Value::Bool(v)) => u64::from(*v) == expected,
            Some(Value::Number(v)) => v.equals_u64(expected),
            _ => false,
        }
    }
    fn route_hash(route: &Object) -> Option<String> {
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
        for key in ["lifecycle_version", "project_memory_contract"] {
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
        Some(format!(
            "{:x}",
            Sha256::digest(Self::canonical(&Value::Object(stable)).as_bytes())
        ))
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
