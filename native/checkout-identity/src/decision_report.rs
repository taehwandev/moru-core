//! owner: rank prepared decision rows and encode cache-only CLI reports.
//! allowed imports: bounded ordered JSON, original cache values and stable ordering.
//! forbidden imports: credentials, provider calls, cache IO, filesystem effects.
//! callers/tests: DecisionCachePlan and test_microsoft_decision.
//! verification: priority buckets, score ordering and stable input ties.
use crate::python_json::{Object, PythonJson, Value as PythonValue};
use serde_json::{json, Value};

pub(crate) struct DecisionReport;

impl DecisionReport {
    pub(crate) fn encode_cache_only(
        report: &Value,
        cached: &[Value],
        digit_limit: usize,
    ) -> Option<String> {
        let PythonValue::Object(mut report) = PythonJson::parse(&report.to_string())? else {
            return None;
        };
        let rows = report.get("results")?.as_array()?;
        if rows.len() != cached.len() {
            return None;
        }
        let rows: Option<Vec<_>> = rows
            .iter()
            .zip(cached)
            .map(|(row, verdict)| {
                let mut row = row.as_object()?.clone();
                if !verdict.is_null() {
                    let content = verdict.get("content")?.as_str()?;
                    let keep_cost = verdict.get("keep_cost")?.as_bool()?;
                    let entry = PythonJson::parse_with_diagnostic(content, Some(digit_limit), None)
                        .ok()??;
                    Self::append_cached(&mut row, &entry, keep_cost)?;
                }
                Some(PythonValue::Object(row))
            })
            .collect();
        report.insert("results".into(), PythonValue::Array(rows?));
        PythonJson::render(&PythonValue::Object(report), false, false)
    }

    fn append_cached(row: &mut Object, entry: &PythonValue, keep_cost: bool) -> Option<()> {
        let result = entry.get("result")?;
        let answers = result.get("answers")?;
        let relevant = answers.get("relevant")?;
        let kind = answers.get("source_kind")?;
        let normalized = object([
            (
                "relevant",
                object([
                    ("type", PythonValue::String("noul".into())),
                    ("noul", relevant.get("noul")?.clone()),
                ]),
            ),
            (
                "source_kind",
                object([
                    ("type", PythonValue::String("choice".into())),
                    ("choice", kind.get("choice")?.clone()),
                    ("probabilities", kind.get("probabilities")?.clone()),
                ]),
            ),
        ]);
        row.insert("evaluated_at".into(), entry.get("evaluated_at")?.clone());
        row.insert(
            "response_model".into(),
            result.get("response_model")?.clone(),
        );
        row.insert(
            "provider".into(),
            match result.get("provider") {
                Some(value @ PythonValue::String(_)) => value.clone(),
                _ => PythonValue::Null,
            },
        );
        row.insert("answers".into(), normalized);
        let cost = if keep_cost {
            result.get("reported_cost_usd")?.clone()
        } else {
            PythonValue::Null
        };
        row.insert("reported_cost_usd".into(), cost);
        Some(())
    }

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

fn object<const N: usize>(fields: [(&str, PythonValue); N]) -> PythonValue {
    let mut result = Object::new();
    for (key, value) in fields {
        result.insert(key.into(), value);
    }
    PythonValue::Object(result)
}
