//! owner: MemoryReview; allowed imports: std/serde_json/MemoryRecord/MemoryTerms/MemoryUpkeep;
//! forbidden imports: IO, process, stores, writes, providers, clock, authority;
//! callers/tests: MemoryProcess and memory_review_tests; verification: original date/report parity.
use crate::{memory_record::MemoryRecord, memory_terms::MemoryTerms, memory_upkeep::MemoryUpkeep};
use serde_json::{json, Value};
use std::collections::HashMap;

pub(crate) struct MemoryReview;
impl MemoryReview {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let today = object.get("today")?.as_str()?;
        let horizon = object.get("horizon")?.as_str()?;
        if !MemoryRecord::date(today) || !MemoryRecord::date(horizon) {
            return None;
        }
        let records = object.get("records")?.as_array()?;
        let live = match operation {
            "review-partition" if object.len() == 4 => {
                for row in records {
                    if row.as_object()?.len() != 2 {
                        return None;
                    }
                }
                (0..records.len()).collect::<Vec<_>>()
            }
            "review-findings" if object.len() == 5 => {
                let mut rows = Vec::with_capacity(records.len());
                for item in records {
                    let row = item.as_object()?;
                    if row.len() != 3 {
                        return None;
                    }
                    let review = row.get("review")?;
                    if !review.is_null() && !review.is_string() {
                        return None;
                    }
                    rows.push(json!({"id":row.get("id")?.as_str()?,"status":row.get("status")?.as_str()?}));
                }
                let selected = MemoryUpkeep::evaluate(
                    "upkeep-live",
                    &json!({
                        "unicode":MemoryTerms::version(),"records":rows,"statuses":object.get("statuses")?
                    }),
                )?;
                selected
                    .get("indices")?
                    .as_array()?
                    .iter()
                    .map(|index| usize::try_from(index.as_u64()?).ok())
                    .collect::<Option<Vec<_>>>()?
            }
            _ => return None,
        };
        let mut dates = HashMap::new();
        for &index in &live {
            let row = &records[index];
            let review = row.get("review")?.as_str()?;
            if !MemoryRecord::date(review) {
                return None;
            }
            dates.insert(row.get("id")?.as_str()?, review);
        }
        let mut expired = Vec::new();
        let mut expiring = Vec::new();
        for &index in &live {
            let review = dates.get(records[index].get("id")?.as_str()?)?;
            if *review <= today {
                expired.push(index);
            } else if *review <= horizon {
                expiring.push(index);
            }
        }
        Some(json!({"live":live,"expired":expired,"expiring":expiring}))
    }
}

#[cfg(test)]
#[path = "memory_review_tests.rs"]
mod tests;
