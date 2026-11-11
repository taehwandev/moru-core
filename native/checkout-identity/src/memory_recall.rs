//! owner: MemoryRecall; allowed imports: JSON/std/MemoryTerms; forbidden imports:
//! filesystem, writes, provider and lifecycle authority; callers/tests: private
//! recall process; verification: source eligibility/rank/negative-input oracles.
use crate::{memory_record::MemoryRecord, memory_terms::MemoryTerms};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
pub(crate) struct MemoryRecall;

impl MemoryRecall {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        match operation {
            "terms" if object.len() == 2 => {
                let (words, paths, modules) = MemoryTerms::terms(object.get("text")?.as_str()?);
                Some(json!({"words":words,"paths":paths,"modules":modules}))
            }
            "recall" if object.len() == 5 => Self::recall(payload),
            _ => None,
        }
    }
    fn recall(payload: &Value) -> Option<Value> {
        let scope = payload.get("scope")?.as_str()?;
        if !MemoryRecord::scope(scope) {
            return None;
        }
        let today = payload.get("today")?.as_str()?;
        if !MemoryRecord::date(today) {
            return None;
        }
        let context = payload.get("context")?.as_str()?;
        let records = payload.get("records")?.as_array()?;
        let mut replaced = BTreeSet::new();
        for record in records {
            record.as_object()?;
            match record.get("replaces") {
                Some(Value::String(value)) => {
                    replaced.insert(value.as_str());
                }
                None | Some(Value::Null) => {}
                _ => return None,
            }
        }
        let query = MemoryTerms::terms(context);
        let mut eligible = Vec::new();
        let mut scores = BTreeMap::new();
        for (index, record) in records.iter().enumerate() {
            let status = record.get("status")?.as_str()?;
            if !["active", "pending", "approved"].contains(&status) {
                continue;
            }
            let id = record.get("id")?.as_str()?;
            if replaced.contains(id) {
                continue;
            }
            let record_scope = record.get("scope")?.as_str()?;
            if record_scope != scope && record_scope != "all" {
                continue;
            }
            let review = record.get("review_on")?.as_str()?;
            if !MemoryRecord::date(review) {
                return None;
            }
            if review <= today {
                continue;
            }
            let mut parts = vec![
                record.get("body")?.as_str()?,
                record.get("source")?.as_str()?,
                record.get("applies_when").map_or(Some(""), Value::as_str)?,
            ];
            if let Some(files) = record.get("source_files") {
                for file in files.as_array()? {
                    parts.push(file.get("path")?.as_str()?);
                }
            }
            scores.insert(id, MemoryTerms::score(&parts.join(" "), &query));
            eligible.push((index, id, record_scope, review));
        }
        // Duplicate ids intentionally share the final dictionary score.
        eligible.retain(|(_, id, _, _)| {
            context
                .chars()
                .all(crate::python_text::PythonText::whitespace)
                || scores[id] > 0
        });
        eligible.sort_by_key(|(_, id, record_scope, review)| {
            (
                std::cmp::Reverse(scores[id]),
                *record_scope != scope,
                *review,
                *id,
            )
        });
        Some(json!({"indices":eligible.into_iter().map(|(i,_,_,_)|i).collect::<Vec<_>>()}))
    }
}

#[cfg(test)]
#[path = "memory_tests.rs"]
mod tests;
