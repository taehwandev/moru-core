//! owner: rank prepared decision report rows and count unscored rows.
//! allowed imports: bounded JSON and stable in-memory ordering.
//! forbidden imports: credentials, provider calls, cache IO, filesystem effects.
//! callers/tests: DecisionCachePlan and test_microsoft_decision.
//! verification: priority buckets, score ordering and stable input ties.
use serde_json::{json, Value};

pub(crate) struct DecisionReport;

impl DecisionReport {
    pub(crate) fn summarize(input: &Value) -> Option<Value> {
        let rows = input.get("rows")?.as_array()?;
        let mut unscored_count = 0;
        let mut ranked = Vec::with_capacity(rows.len());
        for (index, row) in rows.iter().enumerate() {
            let [required, unscored, relevance] = row.as_array()?.as_slice() else {
                return None;
            };
            let required = required.as_bool()?;
            let unscored = unscored.as_bool()?;
            let relevance = relevance.as_f64()?;
            if !(0.0..=1.0).contains(&relevance) {
                return None;
            }
            unscored_count += usize::from(unscored);
            // Compare finite scores and keep -0.0 and +0.0 tied as in Python.
            ranked.push((!(required || unscored), relevance, index));
        }
        ranked.sort_by(
            |(priority_a, relevance_a, _), (priority_b, relevance_b, _)| {
                priority_a.cmp(priority_b).then_with(|| {
                    relevance_b
                        .partial_cmp(relevance_a)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
            },
        );
        let order: Vec<_> = ranked.into_iter().map(|(_, _, index)| index).collect();
        Some(json!({"unscored": unscored_count, "order": order}))
    }
}
