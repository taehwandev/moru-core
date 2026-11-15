//! owner: existing RegistryRead ordinary retention-report argument contract;
//! allowed imports: generated policy JSON, std and serde_json;
//! forbidden imports: target filesystem reads, writes, deletion and policy execution;
//! callers/tests: retention report ingress and sibling parsing tests;
//! verification: offline native argument/default/unsupported-profile tests.
use super::RegistryRead;
use serde_json::{json, Value};
use std::{ffi::OsString, path::Path};

impl RegistryRead {
    pub(super) fn retention_policy() -> Option<Value> {
        let value: Value = serde_json::from_str(include_str!(concat!(
            env!("OUT_DIR"),
            "/retention_policy.json"
        )))
        .ok()?;
        Self::retention_policy_supported(&value).then_some(value)
    }

    pub(super) fn retention_policy_supported(policy: &Value) -> bool {
        let Some(row) = policy.as_object() else {
            return false;
        };
        if row.len() != 12
            || policy["schema_version"].as_u64() != Some(1)
            || policy["run_id_length"].as_u64() != Some(32)
            || policy["registry_schema_version"].as_u64() != Some(1)
        {
            return false;
        }
        for name in ["state_dir", "runs_dir"] {
            let Some(text) = policy[name].as_str() else {
                return false;
            };
            if text.is_empty() || text.contains(['/', '\0']) || [".", ".."].contains(&text) {
                return false;
            }
        }
        for name in ["keep", "abandoned_after_seconds", "orphan_after_seconds"] {
            if policy[name].as_i64().is_none() {
                return false;
            }
        }
        for name in [
            "run_states",
            "holding_states",
            "settled_states",
            "finished_phases",
        ] {
            let Some(values) = policy[name].as_array() else {
                return false;
            };
            if !values.iter().all(Value::is_string) {
                return false;
            }
        }
        true
    }

    pub(super) fn retention_report_args(args: &[OsString], policy: &Value) -> Option<Value> {
        let mut options = json!({"project":std::env::current_dir().ok()?.to_str()?,
            "keep":policy["keep"].as_i64()?.max(0),
            "abandoned_after_seconds":policy["abandoned_after_seconds"].as_i64()?.max(0),
            "orphan_after_seconds":policy["orphan_after_seconds"].as_i64()?.max(0)});
        if args.len() > 64 {
            return None;
        }
        let mut words = args.iter();
        while let Some(word) = words.next() {
            let word = word.to_str()?;
            let (flag, value) = match word.split_once('=') {
                Some(pair) => pair,
                None => (word, words.next()?.to_str()?),
            };
            if value.len() > 4096 {
                return None;
            }
            match flag {
                "--project" => {
                    if value.is_empty()
                        || value.starts_with('-')
                        || value.contains('\0')
                        || !Path::new(value).is_absolute()
                    {
                        return None;
                    }
                    options["project"] = json!(value);
                }
                "--keep" | "--abandoned-after-seconds" | "--orphan-after-seconds" => {
                    let digits = value.strip_prefix(['+', '-']).unwrap_or(value);
                    if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
                        return None;
                    }
                    let number = value.parse::<i64>().ok()?.max(0);
                    options[&flag[2..].replace('-', "_")] = json!(number);
                }
                _ => return None,
            }
        }
        Some(options)
    }
}

#[cfg(test)]
#[path = "registry_retention_args_tests.rs"]
mod tests;
