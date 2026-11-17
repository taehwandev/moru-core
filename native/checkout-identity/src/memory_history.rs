//! owner: MemoryHistory; allowed imports: serde_json, std::collections, MemoryTerms;
//! forbidden imports: filesystem, processes, stores, writes, providers, clock, authority;
//! callers/tests: MemoryProcess history dispatch and memory_history_tests;
//! verification: Python _history traversal, duplicate-order, cycle, cap, and schema parity.
use crate::memory_terms::MemoryTerms;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

const MAX_HISTORY_ITEMS: usize = 20;

struct Row<'a> {
    index: usize,
    id: &'a str,
    replaces: &'a str,
    replaced_by: &'a str,
    fields: Vec<usize>,
}

pub(crate) struct MemoryHistory;

impl MemoryHistory {
    pub(crate) fn evaluate(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        let fields = match object.get("fields") {
            Some(value) => Some(Self::field_names(value)?),
            None => None,
        };
        if object.len() != 3 + usize::from(fields.is_some())
            || object.get("unicode")?.as_str()? != MemoryTerms::version()
        {
            return None;
        }
        let record_id = object.get("record_id")?.as_str()?;
        let records = object.get("records")?.as_array()?;
        let mut ordered: Vec<Row<'_>> = Vec::with_capacity(records.len());
        let mut by_id: HashMap<&str, usize> = HashMap::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 3 + usize::from(fields.is_some()) {
                return None;
            }
            let entry = Row {
                index,
                id: row.get("id")?.as_str()?,
                replaces: Self::link(row.get("replaces")?)?,
                replaced_by: Self::link(row.get("replaced_by")?)?,
                fields: match &fields {
                    Some(fields) => {
                        let keys = Self::field_names(row.get("keys")?)?;
                        fields
                            .iter()
                            .enumerate()
                            .filter_map(|(i, key)| keys.contains(key).then_some(i))
                            .collect()
                    }
                    None => Vec::new(),
                },
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
        let mut projection = Vec::new();
        let mut current = newest;
        let mut seen = HashSet::new();
        while let Some(&slot) = by_id.get(current) {
            if indices.len() >= MAX_HISTORY_ITEMS || !seen.insert(current) {
                break;
            }
            let row = &ordered[slot];
            indices.push(row.index);
            projection.push(&row.fields);
            current = row.replaces;
        }
        Some(if fields.is_some() {
            json!({"indices":indices,"fields":projection})
        } else {
            json!({"indices":indices})
        })
    }

    fn field_names(value: &Value) -> Option<Vec<&str>> {
        let fields = value
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        (fields.iter().collect::<HashSet<_>>().len() == fields.len()).then_some(fields)
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
