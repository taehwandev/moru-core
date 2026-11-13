//! owner: MemoryConsolidation; allowed imports: serde_json, std::collections, MemoryTerms;
//! forbidden imports: filesystem, processes, stores, writes, providers, clock, authority;
//! callers/tests: MemoryProcess consolidation dispatch and memory_consolidation_tests;
//! verification: Python _duplicate_groups and _shared_source_groups parity.
use crate::memory_terms::MemoryTerms;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

const DUPLICATE_JACCARD: f64 = 0.8;

pub(crate) struct MemoryConsolidation;

impl MemoryConsolidation {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 2 || object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let records = object.get("records")?.as_array()?;
        match operation {
            "duplicate-groups" => Self::duplicate_groups(records),
            "shared-source-groups" => Self::shared_source_groups(records),
            _ => None,
        }
    }

    fn duplicate_groups(records: &[Value]) -> Option<Value> {
        let mut ids = Vec::with_capacity(records.len());
        let mut scopes = Vec::with_capacity(records.len());
        let mut token_sets = Vec::with_capacity(records.len());
        for item in records {
            let row = item.as_object()?;
            if row.len() != 3 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            scopes.push(row.get("scope")?.as_str()?);
            let mut set = BTreeSet::new();
            for token in row.get("tokens")?.as_array()? {
                set.insert(token.as_str()?);
            }
            token_sets.push(set);
        }
        let mut parent: Vec<usize> = (0..records.len()).collect();
        for left in 0..records.len() {
            for right in (left + 1)..records.len() {
                if Self::scopes_overlap(scopes[left], scopes[right])
                    && Self::jaccard(&token_sets[left], &token_sets[right]) >= DUPLICATE_JACCARD
                {
                    let left_root = Self::root(&mut parent, left);
                    let right_root = Self::root(&mut parent, right);
                    parent[right_root] = left_root;
                }
            }
        }
        let mut slots: Vec<Option<usize>> = vec![None; records.len()];
        let mut components: Vec<Vec<usize>> = Vec::new();
        for index in 0..records.len() {
            let root = Self::root(&mut parent, index);
            match slots[root] {
                Some(slot) => components[slot].push(index),
                None => {
                    slots[root] = Some(components.len());
                    components.push(vec![index]);
                }
            }
        }
        Some(Self::order_groups(&ids, components))
    }

    fn shared_source_groups(records: &[Value]) -> Option<Value> {
        let mut ids = Vec::with_capacity(records.len());
        let mut slots: BTreeMap<&str, usize> = BTreeMap::new();
        let mut components: Vec<Vec<usize>> = Vec::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            let id = row.get("id")?.as_str()?;
            let source = row.get("source")?.as_str()?;
            ids.push(id);
            match slots.get(source).copied() {
                Some(slot) => components[slot].push(index),
                None => {
                    slots.insert(source, components.len());
                    components.push(vec![index]);
                }
            }
        }
        Some(Self::order_groups(&ids, components))
    }

    fn order_groups(ids: &[&str], components: Vec<Vec<usize>>) -> Value {
        let mut groups: Vec<Vec<usize>> = components
            .into_iter()
            .filter(|members| members.len() > 1)
            .map(|mut members| {
                members.sort_by_key(|&index| ids[index]);
                members
            })
            .collect();
        groups.sort_by(|left, right| {
            left.iter()
                .map(|&index| ids[index])
                .cmp(right.iter().map(|&index| ids[index]))
        });
        json!({ "groups": groups })
    }

    fn scopes_overlap(left: &str, right: &str) -> bool {
        left == right || left == "all" || right == "all"
    }

    fn jaccard(left: &BTreeSet<&str>, right: &BTreeSet<&str>) -> f64 {
        if left.is_empty() || right.is_empty() {
            return 0.0;
        }
        let intersection = left.intersection(right).count();
        let union = left.len() + right.len() - intersection;
        intersection as f64 / union as f64
    }

    fn root(parent: &mut [usize], mut index: usize) -> usize {
        while parent[index] != index {
            parent[index] = parent[parent[index]];
            index = parent[index];
        }
        index
    }
}

#[cfg(test)]
#[path = "memory_consolidation_tests.rs"]
mod tests;
