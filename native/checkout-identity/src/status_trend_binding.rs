//! owner: efficiency trend run and metric binding; allowed imports: JSON and trend windows;
//! forbidden imports: filesystem, SQLite and process execution; callers/tests: trend report parity.
use super::status_trend_windows::TrendWindows;
use serde_json::{json, Map, Value};
use std::collections::HashMap;

pub(super) struct TrendBinding;

struct Run<'a> {
    fields: &'a Map<String, Value>,
    start: &'a str,
    settled: &'a str,
    runtime: &'a str,
    session: &'a str,
    spill: &'a str,
    model: &'a str,
    effort: &'a str,
}

impl<'a> Run<'a> {
    fn read(value: &'a Value) -> Option<Self> {
        Some(Self {
            fields: value.as_object()?,
            start: value.get("started_at")?.as_str()?,
            settled: match value.get("settled_at") {
                None | Some(Value::Null) => "",
                Some(stamp) => stamp.as_str()?,
            },
            runtime: value.get("runtime")?.as_str()?,
            session: value.get("session_id")?.as_str()?,
            spill: value.get("spill_run_id")?.as_str()?,
            model: value.get("stamped_model")?.as_str()?,
            effort: value.get("stamped_effort")?.as_str()?,
        })
    }

    fn output(
        &self,
        model: &str,
        effort: &str,
        metrics: Value,
        single_month: bool,
    ) -> Option<Value> {
        // Ordinary source times are canonical ASCII UTC. Defer non-ASCII slicing and digits.
        if !self.start.is_ascii() {
            return None;
        }
        let ym = self.start.get(..7).unwrap_or("unknown");
        let period = match self.start.get(8..10) {
            Some(day) if single_month && day.bytes().all(|b| b.is_ascii_digit()) => {
                let day: i32 = day.parse().ok()?;
                format!("{ym}-W{}", (1 + (day - 1).div_euclid(7)).min(4))
            }
            _ => ym.to_owned(),
        };
        let mut fields = self.fields.clone();
        fields.insert("model".into(), json!(model));
        fields.insert("reasoning_effort".into(), json!(effort));
        fields.insert("period_bucket".into(), json!(period));
        let Value::Object(metrics) = metrics else {
            return None;
        };
        fields.extend(metrics);
        Some(Value::Object(fields))
    }
}

impl TrendBinding {
    pub(super) fn bind(request: &Value) -> Option<Value> {
        let month = request.get("month")?.as_str()?;
        let events = request.get("spill_events")?.as_object()?;
        let threads = request.get("codex_threads")?.as_object()?;
        let mut indices = HashMap::new();
        let mut sessions: Vec<Vec<Run>> = Vec::new();
        let mut unbound = Vec::new();
        for value in request.get("runs")?.as_array()? {
            let run = Run::read(value)?;
            if run.runtime.is_empty() || run.session.is_empty() {
                unbound.push(run);
            } else {
                let index = *indices
                    .entry((run.runtime, run.session))
                    .or_insert_with(|| {
                        sessions.push(Vec::new());
                        sessions.len() - 1
                    });
                sessions[index].push(run);
            }
        }
        let mut bound = Vec::new();
        for mut runs in sessions {
            runs.sort_by_key(|run| run.start);
            let first = runs.first()?;
            let (model, effort) = match threads.get(first.session) {
                None => ("", "unknown"),
                Some(thread) => {
                    let [model, effort] = thread.as_array()?.as_slice() else {
                        return None;
                    };
                    (model.as_str()?, effort.as_str()?)
                }
            };
            let stamps: Vec<_> = runs.iter().map(|r| [r.start, r.settled]).collect();
            let empty = json!([]);
            let selected = events.get(first.spill).unwrap_or(&empty);
            let mut result = TrendWindows::bind(&json!({"month": month,
                "sessions": [{"runs": stamps, "events": selected}]
            }))?;
            let windows = result.get_mut("windows")?.as_array_mut()?.pop()?;
            let Value::Array(windows) = windows else {
                return None;
            };
            for (run, mut metrics) in runs.iter().zip(windows) {
                if metrics.is_null() {
                    continue;
                }
                let event_model = metrics.as_object_mut()?.remove("event_model")?;
                let model = [run.model, model, event_model.as_str()?]
                    .into_iter()
                    .find(|s| !s.is_empty())
                    .unwrap_or("unknown");
                let effort = [run.effort, if run.runtime == "codex" { effort } else { "" }]
                    .into_iter()
                    .find(|s| !s.is_empty())
                    .unwrap_or("unknown");
                bound.push(run.output(model, effort, metrics, !month.is_empty())?);
            }
        }
        for run in unbound
            .into_iter()
            .filter(|run| run.start.starts_with(month))
        {
            let metrics =
                json!({"turns": 0, "weighted_tokens": 0.0, "raw_tokens": 0, "reasoning_tokens": 0});
            let model = if run.model.is_empty() {
                "unknown"
            } else {
                run.model
            };
            let effort = if run.effort.is_empty() {
                "unknown"
            } else {
                run.effort
            };
            bound.push(run.output(model, effort, metrics, !month.is_empty())?);
        }
        Some(json!({"runs": bound}))
    }
}
