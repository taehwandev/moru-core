//! owner: structure-only merge parent equivalence from caller-owned Git evidence.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: Git execution, lifecycle authority, filesystem and mutation.
//! callers/tests: merge baseline helper and real merge regression fixtures.
//! verification: existing paths, changed index entries and incoming parent precedence.
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};

pub(super) struct StructureMergeBaseline;

impl StructureMergeBaseline {
    pub(super) fn classify(input: &Value) -> Option<Value> {
        let parent = input.get("parent")?.as_str()?;
        if !matches!(parent.len(), 40 | 64)
            || !parent
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        {
            return None;
        }
        let selected = input
            .get("selected")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<HashSet<_>>>()?;
        let [head, incoming] = input.get("refs")?.as_array()?.as_slice() else {
            return None;
        };
        let mut inherited = BTreeMap::new();
        for (refname, counts) in [("HEAD", head), (parent, incoming)] {
            let [changed, existing] = counts.as_array()?.as_slice() else {
                return None;
            };
            let changed: HashSet<_> = Self::paths(changed)?.collect();
            for path in Self::paths(existing)? {
                if selected.contains(path) && !changed.contains(path) {
                    inherited.insert(path, refname);
                }
            }
        }
        Some(json!({"inherited": inherited}))
    }

    fn paths(value: &Value) -> Option<impl Iterator<Item = &str>> {
        let text = value.as_str()?;
        if !text.is_empty() && !text.ends_with('\0') {
            return None;
        }
        Some(text.split_terminator('\0'))
    }
}
