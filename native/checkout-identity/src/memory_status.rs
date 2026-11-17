//! owner: MemoryStatus; allowed imports: JSON/MemorySource/MemoryTerms;
//! forbidden imports: writes, providers, lifecycle authority; callers/tests:
//! memory status probe; verification: cache/error ordering and source oracles.
use crate::{memory_source::MemorySource, memory_terms::MemoryTerms};
use serde_json::{json, Map, Value};

pub(crate) struct MemoryStatus;
impl MemoryStatus {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        if payload.as_object()?.len() != 6
            || payload.get("unicode")?.as_str()? != MemoryTerms::version()
            || payload.get("stdin_eof")?.as_bool()? != true
            || payload.get("encoding")?.as_str()? != "utf-8"
        {
            return None;
        }
        let root = payload.get("root")?.as_str()?;
        let files = payload.get("files")?.as_array()?;
        let mut cache = payload.get("blobs")?.as_object()?.clone();
        if !(1..=4).contains(&files.len())
            || !files.iter().all(|item| {
                item.as_object().is_some_and(|m| m.len() == 2)
                    && item.get("path").is_some_and(Value::is_string)
                    && item.get("blob").is_some_and(Value::is_string)
            })
            || !cache.iter().all(|(path, blob)| {
                blob.is_string() && files.iter().any(|f| f["path"].as_str() == Some(path))
            })
        {
            return None;
        }
        let mut added = Map::new();
        for file in files {
            let path = file["path"].as_str()?;
            if cache.contains_key(path) {
                continue;
            }
            let request = json!({"unicode":payload["unicode"],"root":root,"path":path,
                "tracked":false,"stdin_eof":true,"encoding":"utf-8"});
            let Some(result) = MemorySource::evaluate(&request) else {
                // The original loop resumes after completed hashes, preserving
                // its prefix cache and never replaying an earlier file query.
                return Some(json!({"blobs":added,"result":null}));
            };
            if let Some(error) = result.get("decode_error") {
                return Some(json!({"blobs":added,"decode_error":error}));
            }
            let blob = result.get("blob")?.as_str()?;
            added.insert(path.to_owned(), json!(blob));
            cache.insert(path.to_owned(), json!(blob));
        }
        Some(json!({"blobs":added,"result":Self::aggregate(files, &cache)?}))
    }
    fn aggregate(files: &[Value], cache: &Map<String, Value>) -> Option<Value> {
        let mut unavailable = false;
        let mut changed = false;
        let mut unverified = Vec::new();
        for file in files {
            let path = file["path"].as_str()?;
            let blob = cache.get(path)?.as_str()?;
            if blob.is_empty() {
                unavailable = true;
                unverified.push(path);
            } else if blob != file["blob"].as_str()? {
                changed = true;
                unverified.push(path);
            }
        }
        let status = if changed {
            "changed"
        } else if unavailable {
            "unavailable"
        } else {
            "unchanged"
        };
        Some(if status == "unchanged" {
            json!({"source_status":status})
        } else {
            json!({"source_status":status,"unverified_sources":unverified,
                "warning":format!("Source evidence {status} — verify before use")})
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn payload(files: Value, blobs: Value) -> Value {
        json!({"unicode":MemoryTerms::version(),"root":"/unused-cached-root",
            "files":files,"blobs":blobs,"stdin_eof":true,"encoding":"utf-8"})
    }

    #[test]
    fn changed_precedence_preserves_duplicate_warning_order() {
        let files = json!([{"path":"a","blob":"old"},{"path":"b","blob":"old"},
            {"path":"a","blob":"new"},{"path":"a","blob":"old"}]);
        let result = MemoryStatus::evaluate(&payload(files, json!({"a":"new","b":""}))).unwrap();
        assert_eq!(
            result,
            json!({"blobs":{},"result":{"source_status":"changed",
            "unverified_sources":["a","b","a"],"warning":"Source evidence changed — verify before use"}})
        );
    }

    #[test]
    fn unchanged_and_unavailable_use_existing_cache_without_git() {
        let files = json!([{"path":"a","blob":"expected"}]);
        assert_eq!(
            MemoryStatus::evaluate(&payload(files.clone(), json!({"a":"expected"}))),
            Some(json!({"blobs":{},"result":{"source_status":"unchanged"}}))
        );
        assert_eq!(
            MemoryStatus::evaluate(&payload(files, json!({"a":""}))),
            Some(json!({"blobs":{},"result":{"source_status":"unavailable",
                "unverified_sources":["a"],"warning":"Source evidence unavailable — verify before use"}}))
        );
    }

    #[test]
    fn closed_schema_and_profiles_decline_before_work() {
        let base = payload(json!([{"path":"a","blob":"old"}]), json!({"a":"new"}));
        for (field, value) in [
            ("extra", json!(true)),
            ("unicode", json!("unknown")),
            ("stdin_eof", json!(1)),
            ("encoding", json!("ascii")),
            ("files", json!([])),
            ("blobs", json!({"foreign":"new"})),
            ("blobs", json!({"a":1})),
        ] {
            let mut invalid = base.clone();
            invalid[field] = value;
            assert!(MemoryStatus::evaluate(&invalid).is_none(), "{field}");
        }
    }
}
