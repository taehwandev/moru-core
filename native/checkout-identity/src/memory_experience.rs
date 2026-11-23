//! owner: offline memory evaluation report; allowed imports: std, JSON and
//! existing ranking and projection; forbidden imports: storage, providers or writes;
//! callers/tests: private memory probe and CLI/native Python report parity.
use crate::{
    memory_context::MemoryContext, memory_recall::MemoryRecall, memory_terms::MemoryTerms,
};
use serde_json::{json, Value};
use std::collections::BTreeSet;

const MAX_BATCH_RECORD_VISITS: usize = 32 * 1024;
const MAX_BATCH_OBSERVATION_BYTES: usize = 1024 * 1024;

#[derive(Default)]
struct Counts {
    relevant: usize,
    rendered: usize,
    expected: usize,
    characters: usize,
}

impl Counts {
    fn report(&self) -> Value {
        json!({
            "relevant_rendered": self.relevant,
            "rendered": self.rendered,
            "expected": self.expected,
            "irrelevant_selections": self.rendered - self.relevant,
            "misses": self.expected - self.relevant,
            "payload_characters": self.characters,
        })
    }

    fn add(&mut self, other: &Self) {
        self.relevant += other.relevant;
        self.rendered += other.rendered;
        self.expected += other.expected;
        self.characters += other.characters;
    }
}

pub(super) struct ExperienceMetrics;

impl ExperienceMetrics {
    pub(super) fn evaluate(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 1 {
            return None;
        }
        let observations = object.get("observations")?.as_array()?;
        Self::score(observations)
    }

    pub(super) fn recall(payload: &Value) -> Option<Value> {
        let fields = payload.as_object()?;
        if fields.len() != 5 || fields.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let today = fields.get("today")?.as_str()?;
        let limits = fields.get("limits")?;
        let records = fields.get("records")?.as_array()?;
        let cases = fields.get("cases")?.as_array()?;
        if cases.len().checked_mul(records.len().max(1))? > MAX_BATCH_RECORD_VISITS {
            return None;
        }
        let mut observations = Vec::with_capacity(cases.len());
        let mut observation_bytes = 0;
        for case in cases {
            let scope = string_or(case, "scope", "task")?;
            let mut context = vec![
                string_or(case, "request", "")?,
                string_or(case, "target_summary", "")?,
            ];
            if let Some(paths) = case.get("target_paths") {
                context.extend(strings(paths)?);
            }
            let indices = MemoryRecall::rank(scope, today, &context.join(" "), records)?;
            let ranked: Vec<_> = indices
                .iter()
                .map(|&index| records.get(index)?.get("id")?.as_str())
                .collect::<Option<_>>()?;
            let projected = MemoryContext::project(records, &indices, limits)?;
            let rendered: Vec<_> = projected
                .iter()
                .map(|(item, _)| item.get("id")?.as_str())
                .collect::<Option<_>>()?;
            let payloads: Vec<_> = projected.iter().map(|(_, text)| text).collect();
            observation_bytes += ranked.iter().map(|id| id.len()).sum::<usize>()
                + payloads.iter().map(|text| text.len()).sum::<usize>();
            if observation_bytes > MAX_BATCH_OBSERVATION_BYTES {
                return None;
            }
            observations.push(json!([case, ranked, rendered, payloads]));
        }
        Self::score(&observations)
    }

    fn score(observations: &[Value]) -> Option<Value> {
        let mut cases = Vec::with_capacity(observations.len());
        let mut totals = Counts::default();
        let mut total_characters = 0;
        let mut retrieval_cases = 0;
        for observation in observations {
            let [case, ranked, rendered, payloads] = observation.as_array()?.as_slice() else {
                return None;
            };
            let category = case.get("category")?.as_str()?;
            let expected = case.get("expected_relevant")?;
            let expected_ids = strings(expected)?;
            let rendered_ids = strings(rendered)?;
            let rendered_set: BTreeSet<_> = rendered_ids.iter().copied().collect();
            let expected_set: BTreeSet<_> = expected_ids.iter().copied().collect();
            let raw = strings(payloads)?;
            if rendered_set.len() != rendered_ids.len()
                || rendered_ids.len() != raw.len()
                || expected_set.len() != expected_ids.len()
            {
                return None;
            }
            strings(ranked)?;
            let counts = Counts {
                relevant: rendered_set.intersection(&expected_set).count(),
                rendered: rendered_set.len(),
                expected: expected_set.len(),
                characters: raw.iter().map(|value| value.chars().count()).sum(),
            };
            total_characters += counts.characters;
            if category != "listing" {
                retrieval_cases += 1;
                totals.add(&counts);
            }
            let mut row = json!({
                "id": case.get("id")?.as_str()?,
                "category": category,
                "ranked_ids": ranked,
                "rendered_ids": rendered,
                "expected_relevant": expected,
                "false_inclusions": rendered_set.difference(&expected_set).collect::<Vec<_>>(),
                "missed_ids": expected_set.difference(&rendered_set).collect::<Vec<_>>(),
            });
            row.as_object_mut()?
                .extend(counts.report().as_object()?.clone());
            if let Some(expectation) = case.get("applicability_expectation") {
                row["applicability_expectation"] = Value::String(expectation.as_str()?.into());
            }
            cases.push(row);
        }
        let mut metrics = totals.report();
        metrics["precision"] = json!(ratio(totals.relevant, totals.rendered));
        metrics["recall"] = json!(ratio(totals.relevant, totals.expected));
        Some(json!({
            "case_count": cases.len(), "retrieval_case_count": retrieval_cases,
            "total_payload_characters": total_characters, "metrics": metrics, "cases": cases,
        }))
    }
}

fn string_or<'a>(object: &'a Value, field: &str, default: &'a str) -> Option<&'a str> {
    object.get(field).map_or(Some(default), Value::as_str)
}

fn strings(value: &Value) -> Option<Vec<&str>> {
    value.as_array()?.iter().map(Value::as_str).collect()
}

fn ratio(numerator: usize, denominator: usize) -> Option<f64> {
    (denominator != 0).then(|| numerator as f64 / denominator as f64)
}
