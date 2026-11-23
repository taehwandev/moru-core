//! owner: first-error validation of execution capsule and preflight record shapes.
//! allowed imports: serde JSON and the completion probe's numeric compatibility check.
//! forbidden imports: filesystem, identity/evidence authorization, writes and providers.
//! callers/tests: completion probe and native capsule shape parity fixtures.
//! verification: exact diagnostic precedence, legacy scalar types and filename rules.
use super::capsule_json_integers;
use serde_json::{json, Map, Value};

type Record = Map<String, Value>;
type Check = Option<Option<&'static str>>;

const PREFLIGHT_FIELDS: [&str; 4] = [
    "schema_version",
    "route_fingerprint",
    "request_fingerprint",
    "required_docs",
];
const CAPSULE_FIELDS: [&str; 7] = [
    "created_at",
    "phase",
    "preflight_evidence",
    "project_git",
    "rules_git",
    "gate_ledger",
    "reuse_policy",
];

pub(super) const PREFLIGHT_VERSION: u64 = 1;
const CAPSULE_VERSION: u64 = 4;

pub(super) struct CapsuleShape;

impl CapsuleShape {
    pub(super) fn validate(request: &Value) -> Option<Value> {
        let value = request.get("record")?;
        if !capsule_json_integers(value) {
            return None;
        }
        let first = match request.get("kind")?.as_str()? {
            "capsule" => Self::capsule(value)?,
            "preflight" => Self::preflight(value),
            _ => return None,
        };
        Some(json!({"failures": first.into_iter().collect::<Vec<_>>()}))
    }

    fn capsule(value: &Value) -> Check {
        let record = value.as_object()?;
        let failure = if record.is_empty() {
            "execution capsule is missing"
        } else if record.get("invalid_json").is_some_and(Self::truthy) {
            "execution capsule is not valid JSON"
        } else if !Self::version(record, CAPSULE_VERSION) {
            "execution capsule has an unsupported schema version"
        } else if record.keys().any(|key| {
            !PREFLIGHT_FIELDS.contains(&key.as_str()) && !CAPSULE_FIELDS.contains(&key.as_str())
        }) {
            "execution capsule contains unsupported fields"
        } else if !Self::valid_phase(record.get("phase"))? {
            "execution capsule has an invalid phase"
        } else if !Self::nonempty(record.get("created_at")) {
            "execution capsule created_at is missing"
        } else if !Self::digest(record.get("route_fingerprint")) {
            "execution capsule route fingerprint is malformed"
        } else if !Self::digest(record.get("request_fingerprint")) {
            "execution capsule request fingerprint is malformed"
        } else if !Self::file_hash(record.get("preflight_evidence")) {
            "execution capsule preflight evidence is malformed"
        } else if !Self::git(record.get("project_git")) || !Self::git(record.get("rules_git")) {
            "execution capsule git state is malformed"
        } else if record.get("reuse_policy")
            != Some(&json!({
                "condition": "ready_and_valid",
                "gate_effect": "none",
                "ledger_owner": "parent",
                "worker_may_skip": ["route", "preflight"],
                "worker_may_reuse": ["required-doc-manifest"]
            }))
        {
            "execution capsule reuse policy does not match"
        } else if !Self::docs(record.get("required_docs")) {
            "execution capsule required docs are malformed"
        } else if record.contains_key("gate_ledger") && !Self::file_hash(record.get("gate_ledger"))
        {
            "execution capsule gate ledger is malformed"
        } else {
            return Some(None);
        };
        Some(Some(failure))
    }

    fn preflight(value: &Value) -> Option<&'static str> {
        let Some(record) = value
            .as_object()
            .filter(|record| Self::exact(record, &PREFLIGHT_FIELDS))
        else {
            return Some("preflight snapshot is malformed");
        };
        if !Self::version(record, PREFLIGHT_VERSION) {
            Some("preflight snapshot has an unsupported schema version")
        } else if !Self::digest(record.get("route_fingerprint")) {
            Some("preflight snapshot route fingerprint is malformed")
        } else if !Self::digest(record.get("request_fingerprint")) {
            Some("preflight snapshot request fingerprint is malformed")
        } else if !Self::docs(record.get("required_docs")) {
            Some("preflight snapshot required docs are malformed")
        } else {
            None
        }
    }

    fn exact(record: &Record, fields: &[&str]) -> bool {
        record.len() == fields.len() && fields.iter().all(|key| record.contains_key(*key))
    }

    fn version(record: &Record, expected: u64) -> bool {
        match record.get("schema_version") {
            Some(Value::Bool(value)) => u64::from(*value) == expected,
            Some(value) => value.as_u64() == Some(expected),
            None => false,
        }
    }

    fn valid_phase(value: Option<&Value>) -> Option<bool> {
        match value {
            // Python set membership raises for unhashable values.
            Some(Value::Array(_) | Value::Object(_)) => None,
            _ => Some(matches!(
                value.and_then(Value::as_str),
                Some("preflight" | "ready")
            )),
        }
    }

    fn truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(value) => *value,
            Value::Number(value) => value.as_u64() != Some(0),
            Value::String(value) => !value.is_empty(),
            Value::Array(value) => !value.is_empty(),
            Value::Object(value) => !value.is_empty(),
        }
    }

    fn nonempty(value: Option<&Value>) -> bool {
        value
            .and_then(Value::as_str)
            .is_some_and(|text| !text.is_empty())
    }

    fn digest(value: Option<&Value>) -> bool {
        value.and_then(Value::as_str).is_some_and(|text| {
            text.len() == 64
                && text
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
    }

    fn file_hash(value: Option<&Value>) -> bool {
        value.and_then(Value::as_object).is_some_and(|record| {
            Self::exact(record, &["filename", "sha256"])
                && record["filename"]
                    .as_str()
                    .is_some_and(|text| !text.is_empty() && text != "." && !text.contains('/'))
                && Self::digest(record.get("sha256"))
        })
    }

    fn git(value: Option<&Value>) -> bool {
        value.and_then(Value::as_object).is_some_and(|record| {
            Self::exact(
                record,
                &["head", "worktree_fingerprint", "worktree_signature"],
            ) && Self::nonempty(record.get("head"))
                && Self::digest(record.get("worktree_fingerprint"))
                && Self::digest(record.get("worktree_signature"))
        })
    }

    fn docs(value: Option<&Value>) -> bool {
        value.and_then(Value::as_array).is_some_and(|items| {
            items.iter().all(|item| {
                item.as_object().is_some_and(|record| {
                    Self::exact(record, &["path", "size_bytes", "sha256"])
                        && Self::nonempty(record.get("path"))
                        && (record["size_bytes"].is_boolean()
                            || record["size_bytes"].as_u64().is_some())
                        && Self::digest(record.get("sha256"))
                })
            })
        })
    }
}
