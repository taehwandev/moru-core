//! owner: offline memory evaluation report metrics; allowed imports: std and JSON;
//! forbidden imports: memory storage, ranking, providers or state writes;
//! callers/tests: private memory probe and CLI/native Python report parity.
use serde_json::{json, Value};
use std::collections::BTreeSet;

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

fn strings(value: &Value) -> Option<Vec<&str>> {
    value.as_array()?.iter().map(Value::as_str).collect()
}

fn ratio(numerator: usize, denominator: usize) -> Option<f64> {
    (denominator != 0).then(|| numerator as f64 / denominator as f64)
}
