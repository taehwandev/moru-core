//! owner: offline behavior evaluator trace scoring; allowed imports: std collections and serde_json.
//! forbidden imports: file IO, providers, subprocesses or lifecycle decisions.
//! callers/tests: native offline grader and ordered Python scoring fixtures.
//! verification: ordered failure evidence and missing-run behavior.
use serde_json::Value;
use std::collections::HashMap;

pub(crate) struct BehaviorEval;

impl BehaviorEval {
    // The caller validates case and event schemas before grading. Keep lookup
    // order independent of map iteration so failure output follows the case.
    pub(crate) fn trace_failures(case: &Value, events: Option<&[Value]>) -> Option<Vec<String>> {
        let Some(events) = events else {
            return Some(vec!["missing_run".into()]);
        };
        let expected_status = case.get("expected_status")?.as_str()?;
        let max_prompts = case.get("max_prompts")?.as_u64()?;
        let mut first = HashMap::new();
        let mut counts = HashMap::new();
        let mut finals = Vec::new();
        let mut last = None;
        for (index, event) in events.iter().enumerate() {
            let kind = event.get("kind")?.as_str()?;
            first.entry(kind).or_insert(index);
            *counts.entry(kind).or_insert(0_u64) += 1;
            if kind == "final" {
                finals.push(event.get("status")?.as_str()?);
            }
            last = Some(kind);
        }
        let mut failures = Vec::new();
        if let [status] = finals.as_slice() {
            if *status != expected_status {
                failures.push(format!("final_status:{status}!=expected:{expected_status}"));
            }
            if last != Some("final") {
                failures.push("events_after_final".into());
            }
        } else {
            failures.push(format!("final_event_count:{}", finals.len()));
        }
        let prompts = counts.get("prompt_submitted").copied().unwrap_or(0);
        if prompts > max_prompts {
            failures.push(format!("max_prompts_exceeded:{prompts}>{max_prompts}"));
        }
        for (field, expected, error) in [
            ("required_events", true, "missing_required_event"),
            ("forbidden_events", false, "forbidden_event"),
        ] {
            for kind in case.get(field)?.as_array()? {
                let kind = kind.as_str()?;
                if first.contains_key(kind) != expected {
                    failures.push(format!("{error}:{kind}"));
                }
            }
        }
        for pair in case.get("ordered_pairs")?.as_array()? {
            let [a, b] = pair.as_array()?.as_slice() else {
                return None;
            };
            let (a, b) = (a.as_str()?, b.as_str()?);
            match (first.get(a), first.get(b)) {
                (Some(_), Some(_)) if a == b && counts[a] < 2 => {
                    failures.push(format!("ordered_pair_missing:{a}->{b}"));
                }
                (Some(left), Some(right)) if a != b && left >= right => {
                    failures.push(format!("ordered_pair_out_of_order:{a}->{b}"));
                }
                (Some(_), Some(_)) => {}
                _ => failures.push(format!("ordered_pair_missing:{a}->{b}")),
            }
        }
        Some(failures)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn trace_failures_preserve_python_order_and_repeated_kind_semantics() {
        let case = json!({
            "expected_status":"ok","max_prompts":0,
            "required_events":["missing","missing"],"forbidden_events":["after"],
            "ordered_pairs":[["after","prompt_submitted"],["final","final"],
                             ["prompt_submitted","prompt_submitted"]]
        });
        let events = json!([
            {"kind":"prompt_submitted"},{"kind":"final","status":"blocked"},
            {"kind":"prompt_submitted"},{"kind":"after"}
        ]);
        assert_eq!(
            BehaviorEval::trace_failures(&case, events.as_array().map(Vec::as_slice)).unwrap(),
            [
                "final_status:blocked!=expected:ok",
                "events_after_final",
                "max_prompts_exceeded:2>0",
                "missing_required_event:missing",
                "missing_required_event:missing",
                "forbidden_event:after",
                "ordered_pair_out_of_order:after->prompt_submitted",
                "ordered_pair_missing:final->final"
            ]
        );
        assert_eq!(
            BehaviorEval::trace_failures(&case, None).unwrap(),
            ["missing_run"]
        );
    }
}
