//! Owner: semantic progress fingerprint and bounded stagnation diagnosis.
//! Allowed: std, serde_json, sha2. Forbidden: clocks, writes, retries/authority.
//! Callers/tests: completion_process; native progress and Stop integration tests.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub(crate) struct Progress;

impl Progress {
    pub(crate) fn inspect(value: &Value) -> Option<Value> {
        let work = value.get("work")?.as_object()?;
        let mut remaining = BTreeSet::new();
        for item in work.get("remaining_work")?.as_array()? {
            remaining.insert(
                serde_json::to_string(&json!([
                    item.get("checkpoint")?.as_str()?,
                    item.get("action")?.as_str()?
                ]))
                .ok()?,
            );
        }
        let blockers: BTreeSet<_> = work
            .get("blockers")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<_>>()?;
        let mut gates = BTreeMap::new();
        for entry in value.get("gates")?.as_array()? {
            gates.insert(entry.get("gate")?.as_str()?, entry.get("status")?.as_str()?);
        }
        let mut requirements = BTreeSet::new();
        if let Some(items) = work
            .get("requirements")
            .and_then(|v| v.get("items"))
            .and_then(Value::as_array)
        {
            for item in items {
                let paths: BTreeSet<_> = item
                    .get("artifacts")?
                    .as_array()?
                    .iter()
                    .map(Value::as_str)
                    .collect::<Option<_>>()?;
                requirements.insert(
                    serde_json::to_string(&json!([
                        item.get("id")?,
                        item.get("outcome")?,
                        item.get("owner")?,
                        item.get("gate")?,
                        paths
                    ]))
                    .ok()?,
                );
            }
        }
        let semantic =
            serde_json::to_vec(&json!([remaining, blockers, gates, requirements])).ok()?;
        let fingerprint = format!("{:x}", Sha256::digest(semantic));
        let previous = value.get("previous");
        let repeats = if previous
            .and_then(|v| v.get("fingerprint"))
            .and_then(Value::as_str)
            == Some(&fingerprint)
        {
            previous?.get("repeats")?.as_u64()?.min(1000) + 1
        } else {
            0
        };
        Some(json!({"fingerprint":fingerprint,"repeats":repeats,"stalled":repeats>=2}))
    }
}
