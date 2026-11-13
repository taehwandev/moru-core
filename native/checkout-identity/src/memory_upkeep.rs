//! owner: MemoryUpkeep; allowed imports: std collections, serde_json, MemoryTerms;
//! forbidden imports: IO, process, store, writes, providers, clock, authority;
//! callers/tests: MemoryProcess and memory_upkeep_tests; verification: source parity.
use crate::memory_terms::MemoryTerms;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

pub(crate) struct MemoryUpkeep;
impl MemoryUpkeep {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let records = object.get("records")?.as_array()?;
        match operation {
            "upkeep-live" if object.len() == 3 => Self::live(records, object.get("statuses")?),
            "upkeep-replacements" if object.len() == 2 => Self::replacements(records),
            "upkeep-startup" if object.len() == 3 => Self::startup(records, object.get("today")?),
            _ => None,
        }
    }

    fn live(records: &[Value], statuses: &Value) -> Option<Value> {
        let allowed = statuses
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<HashSet<_>>>()?;
        let mut ids = Vec::with_capacity(records.len());
        let mut indices = Vec::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            if allowed.contains(row.get("status")?.as_str()?) {
                indices.push(index);
            }
        }
        indices.sort_by_key(|&index| ids[index]);
        Some(json!({"indices": indices}))
    }

    fn replacements(records: &[Value]) -> Option<Value> {
        let mut ids = Vec::with_capacity(records.len());
        let mut links: HashMap<&str, Vec<usize>> = HashMap::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            if let Some(target) = Self::link(row.get("replaces")?)? {
                if !target.is_empty() {
                    links.entry(target).or_default().push(index);
                }
            }
        }
        let mut findings = Vec::new();
        for (index, id) in ids.iter().enumerate() {
            if let Some(members) = links.get(*id) {
                let mut ordered = members.clone();
                ordered.sort_by_key(|&member| ids[member]);
                findings.push(json!({"index":index,"replacements":ordered}));
            }
        }
        Some(json!({"findings":findings}))
    }

    fn startup(records: &[Value], today: &Value) -> Option<Value> {
        let today = today.as_i64()?;
        if !(1..=3652059).contains(&today) {
            return None;
        }
        let mut bodies: HashMap<&str, HashMap<&str, usize>> = HashMap::new();
        let mut sources: HashMap<&str, usize> = HashMap::new();
        let mut replaced = HashSet::new();
        let mut ids = Vec::with_capacity(records.len());
        let mut expired = 0;
        for item in records {
            let row = item.as_object()?;
            if row.len() != 6 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            let body = row.get("body")?.as_str()?;
            let scope = row.get("scope")?.as_str()?;
            if !body.is_empty() {
                *bodies.entry(body).or_default().entry(scope).or_default() += 1;
            }
            *sources.entry(row.get("source")?.as_str()?).or_default() += 1;
            if let Some(target) = Self::link(row.get("replaces")?)? {
                replaced.insert(target);
            }
            let review = row.get("review")?.as_i64()?;
            if !(1..=3652059).contains(&review) {
                return None;
            }
            expired += usize::from(review <= today);
        }
        let exact_duplicates: usize = bodies
            .values()
            .map(|counts| {
                if counts.contains_key("all") {
                    usize::from(counts.values().sum::<usize>() > 1)
                } else {
                    counts.values().filter(|&&count| count > 1).count()
                }
            })
            .sum();
        Some(json!({"counts": {
            "expired":expired,"exact_duplicates":exact_duplicates,
            "shared_source":sources.values().filter(|&&count| count > 1).count(),
            "unfinished":ids.iter().filter(|id| replaced.contains(**id)).count()
        }}))
    }

    fn link(value: &Value) -> Option<Option<&str>> {
        match value {
            Value::Null => Some(None),
            Value::String(text) => Some(Some(text)),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "memory_upkeep_tests.rs"]
mod tests;
