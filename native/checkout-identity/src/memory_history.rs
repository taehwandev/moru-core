//! owner: MemoryHistory; allowed imports: serde_json, std::collections, MemoryTerms;
//! forbidden imports: filesystem, processes, stores, writes, providers, clock, authority;
//! callers/tests: MemoryProcess history dispatch and memory_history_tests;
//! verification: Python _history traversal, duplicate-order, cycle, cap, and schema parity.
use crate::memory_terms::MemoryTerms;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

const MAX_HISTORY_ITEMS: usize = 20;

#[derive(Clone, Copy)]
struct Row<'a> {
    index: usize,
    id: &'a str,
    replaces: &'a str,
    replaced_by: &'a str,
}

pub(crate) struct MemoryHistory;

impl MemoryHistory {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 3 || object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let record_id = object.get("record_id")?.as_str()?;
        let records = object.get("records")?.as_array()?;
        let mut ordered: Vec<Row<'_>> = Vec::with_capacity(records.len());
        let mut by_id: HashMap<&str, usize> = HashMap::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 3 {
                return None;
            }
            let entry = Row {
                index,
                id: row.get("id")?.as_str()?,
                replaces: Self::link(row.get("replaces")?)?,
                replaced_by: Self::link(row.get("replaced_by")?)?,
            };
            if let Some(&slot) = by_id.get(entry.id) {
                ordered[slot] = entry;
            } else {
                by_id.insert(entry.id, ordered.len());
                ordered.push(entry);
            }
        }
        if !by_id.contains_key(record_id) {
            return None;
        }
        let mut following: HashMap<&str, &str> = HashMap::new();
        for row in &ordered {
            if !row.replaces.is_empty() {
                following.insert(row.replaces, row.id);
            }
        }
        let mut newest = record_id;
        let mut seen = HashSet::from([record_id]);
        loop {
            let row = &ordered[*by_id.get(newest)?];
            let later = if !row.replaced_by.is_empty() {
                Some(row.replaced_by)
            } else {
                following.get(newest).copied()
            };
            let Some(next) = later else {
                break;
            };
            if !by_id.contains_key(next) || !seen.insert(next) {
                break;
            }
            newest = next;
        }
        let mut indices = Vec::new();
        let mut current = newest;
        let mut seen = HashSet::new();
        while let Some(&slot) = by_id.get(current) {
            if indices.len() >= MAX_HISTORY_ITEMS || !seen.insert(current) {
                break;
            }
            let row = &ordered[slot];
            indices.push(row.index);
            current = row.replaces;
        }
        Some(json!({ "indices": indices }))
    }

    fn link(value: &Value) -> Option<&str> {
        match value {
            Value::Null => Some(""),
            Value::String(text) => Some(text.as_str()),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "memory_history_tests.rs"]
mod tests;
