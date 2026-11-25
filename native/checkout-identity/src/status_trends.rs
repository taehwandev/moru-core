//! owner: efficiency trend grouping and summaries; allowed: typed metrics, JSON, exact mean;
//! forbidden: database reads, filesystem access, clocks, session IDs and state changes;
//! callers/tests: status trend report and synthetic Python/Rust parity.
use crate::python_mean::PythonMean;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;

const COHORT: &[&str] = &["runtime", "model", "reasoning_effort", "same_work_mode"];
const ROUTE: &[&str] = &["route", "same_work_mode"];
const PERIOD: &[&str] = &[
    "period_bucket",
    "runtime",
    "model",
    "reasoning_effort",
    "same_work_mode",
];

pub(super) struct StatusTrends;

struct Metric<'a> {
    row: &'a Value,
    turns: i64,
    weighted_m: f64,
    reasoning: i64,
    docs: i64,
    reused: i64,
    completed: bool,
}

impl<'a> Metric<'a> {
    fn read(row: &'a Value) -> Option<Self> {
        let turns = row.get("turns")?.as_i64()?;
        let weighted_m = row.get("weighted_tokens")?.as_f64()? / 1_000_000.0;
        if turns <= 0 || !weighted_m.is_finite() {
            return None;
        }
        Some(Self {
            row,
            turns,
            weighted_m,
            reasoning: row.get("reasoning_tokens")?.as_i64()?,
            docs: row.get("required_docs_count")?.as_i64()?,
            reused: row.get("reused_gate_count")?.as_i64()?,
            completed: row.get("state")?.as_str()? == "completed",
        })
    }
}

impl StatusTrends {
    pub(super) fn summarize(request: &Value) -> Option<Value> {
        let metrics = request
            .get("matched")?
            .as_array()?
            .iter()
            .map(Metric::read)
            .collect::<Option<Vec<_>>>()?;
        Some(json!({
            "cohorts": Self::group(&metrics, COHORT, false)?,
            "route_cohorts": Self::group(&metrics, ROUTE, false)?,
            "period_trends": Self::group(&metrics, PERIOD, true)?,
        }))
    }

    fn group(metrics: &[Metric<'_>], labels: &[&str], chronological: bool) -> Option<Vec<Value>> {
        let mut groups = BTreeMap::<Vec<&str>, Vec<usize>>::new();
        for (index, metric) in metrics.iter().enumerate() {
            let key = labels
                .iter()
                .map(|name| metric.row.get(*name)?.as_str())
                .collect::<Option<Vec<_>>>()?;
            groups.entry(key).or_default().push(index);
        }
        let mut groups: Vec<_> = groups.into_iter().collect();
        groups.sort_by(|(left, a), (right, b)| {
            if chronological {
                left[0]
                    .cmp(right[0])
                    .then_with(|| b.len().cmp(&a.len()))
                    .then_with(|| a[0].cmp(&b[0]))
            } else {
                b.len().cmp(&a.len()).then_with(|| left.cmp(right))
            }
        });
        groups
            .into_iter()
            .map(|(key, indexes)| {
                let rows: Vec<_> = indexes.into_iter().map(|index| &metrics[index]).collect();
                let mut summary = Self::summary(&rows)?;
                for (label, value) in labels.iter().zip(key) {
                    let name = if *label == "period_bucket" {
                        "period"
                    } else {
                        label
                    };
                    summary.insert(name.to_string(), json!(value));
                }
                Some(Value::Object(summary))
            })
            .collect()
    }

    fn summary(rows: &[&Metric<'_>]) -> Option<Map<String, Value>> {
        let total_turns = Self::total(rows.iter().map(|row| row.turns))?;
        let reasoning = Self::total(rows.iter().map(|row| row.reasoning))?;
        let turns = Self::measure(rows.iter().map(|row| row.turns as f64), 1)?;
        let weighted = Self::measure(rows.iter().map(|row| row.weighted_m), 3)?;
        let value = json!({
            "run_count": rows.len(),
            "completed_runs": rows.iter().filter(|row| row.completed).count(),
            "turns_p50": turns[0], "turns_p90": turns[1], "turns_mean": turns[2],
            "weighted_tokens_m_p50": weighted[0], "weighted_tokens_m_p90": weighted[1],
            "weighted_tokens_m_mean": weighted[2],
            "avg_required_docs": Self::integer_mean(rows.iter().map(|row| row.docs), rows.len())?,
            "avg_reused_gates": Self::integer_mean(rows.iter().map(|row| row.reused), rows.len())?,
            "reasoning_tokens_per_turn": Self::rounded(reasoning as f64 / total_turns as f64, 1)?,
        });
        match value {
            Value::Object(map) => Some(map),
            _ => None,
        }
    }

    fn measure(values: impl Iterator<Item = f64>, digits: usize) -> Option<[f64; 3]> {
        let mut values: Vec<_> = values.collect();
        values.sort_by(|left, right| left.partial_cmp(right).unwrap());
        let length = values.len();
        let middle = length / 2;
        let median = if length % 2 == 0 {
            (values[middle - 1] + values[middle]) / 2.0
        } else {
            values[middle]
        };
        let rank = (((length - 1) as f64) * 0.9).round_ties_even() as usize;
        Some([
            Self::rounded(median, digits)?,
            Self::rounded(values[rank], digits)?,
            Self::rounded(PythonMean::calculate(&values)?, digits)?,
        ])
    }

    fn integer_mean(values: impl Iterator<Item = i64>, length: usize) -> Option<Value> {
        let total = Self::total(values)?;
        let length = i64::try_from(length).ok()?;
        if total % length == 0 {
            return Some(json!(total / length));
        }
        Some(json!(Self::rounded(total as f64 / length as f64, 2)?))
    }

    fn total(mut values: impl Iterator<Item = i64>) -> Option<i64> {
        let total = values.try_fold(0i64, i64::checked_add)?;
        (total.unsigned_abs() <= (1 << 53)).then_some(total)
    }

    fn rounded(value: f64, digits: usize) -> Option<f64> {
        value.is_finite().then_some(())?;
        format!("{value:.digits$}").parse().ok()
    }
}
