//! owner: read-only required-document drift diagnostics.
//! allowed imports: bounded document observations, serde JSON and std.
//! forbidden imports: evidence admission or issuance, writes and providers.
//! callers/tests: capsule validation through the completion probe.
//! verification: ordered duplicate observations and Python receipt parity.
use crate::doc_transcript::DocTranscript;
use serde_json::{json, Value};
use std::path::Path;

pub(super) struct CapsuleDocDrift;

impl CapsuleDocDrift {
    pub(super) fn compare(payload: &Value) -> Option<Value> {
        let rules = Path::new(payload.get("rules")?.as_str()?);
        let recorded = payload.get("recorded")?.as_array()?;
        let updates = payload.get("updates")?.as_object()?;
        let names = recorded
            .iter()
            .map(|item| item.get("path")?.as_str())
            .collect::<Option<Vec<_>>>()?;
        let current = DocTranscript::hash_documents(rules, &names)?;
        let mut failures = Vec::new();
        for ((prior, now), name) in recorded.iter().zip(current.as_array()?).zip(names) {
            let prior_hash = prior.get("sha256")?.as_str()?;
            let now_hash = now.get("sha256")?.as_str()?;
            let now_size = now.get("size_bytes")?.as_u64()?;
            if let Some((baseline, final_hash, final_size)) = Self::receipt(updates.get(name))? {
                if prior_hash != baseline {
                    failures.push(format!(
                        "execution capsule required doc documentation baseline does not match: {name}"
                    ));
                } else {
                    if now_size != final_size.parse::<u64>().ok()? || now_hash != final_hash {
                        failures.push(format!(
                            "execution capsule required doc changed after documentation evidence: {name}"
                        ));
                    }
                    continue;
                }
            }
            let size_matches = match prior.get("size_bytes")? {
                Value::Bool(size) => u64::from(*size) == now_size,
                Value::Number(size) if size.is_u64() || size.is_i64() => {
                    size.as_u64() == Some(now_size)
                }
                _ => return None,
            };
            if !size_matches {
                failures.push(format!(
                    "execution capsule required doc size changed: {name}"
                ));
            }
            if now_hash != prior_hash {
                failures.push(format!(
                    "execution capsule required doc hash changed: {name}"
                ));
            }
        }
        Some(json!({"failures": failures}))
    }

    fn receipt(value: Option<&Value>) -> Option<Option<(&str, &str, &str)>> {
        let Some(value) = value else {
            return Some(None);
        };
        let fields = value.as_object()?;
        if fields
            .get("artifact_receipt_version")
            .and_then(Value::as_str)
            != Some("1")
        {
            return Some(None);
        }
        let baseline = fields.get("baseline_sha256").and_then(Self::sha256);
        let final_hash = fields.get("final_sha256").and_then(Self::sha256);
        let size = fields.get("final_size_bytes").and_then(Value::as_str);
        let (Some(baseline), Some(final_hash), Some(size)) = (baseline, final_hash, size) else {
            return Some(None);
        };
        // Python isdigit accepts some Unicode digits that int interprets
        // differently or rejects. Wide inputs also use Python's int policy.
        if !size.is_ascii() || size.len() > 20 {
            return None;
        }
        if size.is_empty() || !size.bytes().all(|byte| byte.is_ascii_digit()) {
            return Some(None);
        }
        Some(Some((baseline, final_hash, size)))
    }

    fn sha256(value: &Value) -> Option<&str> {
        value.as_str().filter(|text| {
            text.len() == 64
                && text
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
    }
}
