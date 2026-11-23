//! owner: LedgerBinding; allowed imports: route identity, PythonJson, sha2 and std;
//! forbidden imports: state mutation, subprocess; callers/tests: NextLedger;
//! verification: canonical route/preflight identity fixtures.
use super::super::paths::NextPaths;
use crate::python_json::{Object, PythonJson as Py, Value};
use crate::route_identity::RouteIdentity;
use sha2::{Digest, Sha256};
use std::{fs, path::Path};
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
        let path = NextPaths::expand(Path::new(&recorded), &NextPaths::home()?)?;
        match path.canonicalize() {
            Ok(_) if NextPaths::existing(&path)?.as_path() == evidence => {}
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
        let fingerprint = RouteIdentity::route_hash(route)?;
        Some(ledger.get("route_fingerprint").and_then(Value::as_str) == Some(fingerprint.as_str()))
    }
    pub fn equals(value: Option<&Value>, expected: u64) -> bool {
        match value {
            Some(Value::Bool(v)) => u64::from(*v) == expected,
            Some(Value::Number(v)) => v.equals_u64(expected),
            _ => false,
        }
    }
}
