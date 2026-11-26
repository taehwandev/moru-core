//! owner: ordered trend event windows; allowed: JSON and the shared Python sum;
//! forbidden: databases, filesystem reads, session identifiers and state effects;
//! callers/tests: observability time binding and synthetic boundary parity.
use crate::{
    python_json::{Number, Value as PythonValue},
    python_sum::PythonSum,
};
use serde_json::{json, Value};

pub(super) struct TrendWindows;

struct Run<'a> {
    start: &'a str,
    settled: &'a str,
}

impl<'a> Run<'a> {
    fn read(value: &'a Value) -> Option<Self> {
        let [start, settled] = value.as_array()?.as_slice() else {
            return None;
        };
        Some(Self {
            start: start.as_str()?,
            settled: settled.as_str()?,
        })
    }

    fn end(&self, next_start: Option<&'a str>) -> &'a str {
        if self.settled > self.start && next_start.is_none_or(|next| self.settled < next) {
            self.settled
        } else {
            next_start.unwrap_or("9999-99-99")
        }
    }
}

struct Event<'a> {
    stamp: &'a str,
    model: &'a str,
    weight: PythonValue,
    raw: i64,
    reasoning: i64,
}

impl<'a> Event<'a> {
    fn read(value: &'a Value) -> Option<Self> {
        let [stamp, model, weight, raw, reasoning] = value.as_array()?.as_slice() else {
            return None;
        };
        let weight = weight.as_number()?;
        if !weight.is_f64() {
            return None;
        }
        Some(Self {
            stamp: stamp.as_str()?,
            model: model.as_str()?,
            weight: PythonValue::Number(Number::Float(weight.as_f64()?)),
            raw: raw.as_i64()?,
            reasoning: reasoning.as_i64()?,
        })
    }
}

impl TrendWindows {
    pub(super) fn bind(request: &Value) -> Option<Value> {
        let month = request.get("month")?.as_str()?;
        let windows = request
            .get("sessions")?
            .as_array()?
            .iter()
            .map(|session| Self::session(session, month))
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"windows": windows}))
    }

    fn session(session: &Value, month: &str) -> Option<Vec<Value>> {
        let runs = session
            .get("runs")?
            .as_array()?
            .iter()
            .map(Run::read)
            .collect::<Option<Vec<_>>>()?;
        let events = session
            .get("events")?
            .as_array()?
            .iter()
            .map(Event::read)
            .collect::<Option<Vec<_>>>()?;
        if !runs.windows(2).all(|pair| pair[0].start <= pair[1].start)
            || !events.windows(2).all(|pair| pair[0].stamp <= pair[1].stamp)
        {
            return None;
        }
        runs.iter()
            .enumerate()
            .map(|(index, run)| {
                if !run.start.starts_with(month) {
                    return Some(Value::Null);
                }
                let end = run.end(runs.get(index + 1).map(|next| next.start));
                if run.start >= end {
                    return Self::metrics(&[]);
                }
                let first = events.partition_point(|event| event.stamp < run.start);
                let last = events.partition_point(|event| event.stamp < end);
                Self::metrics(&events[first..last])
            })
            .collect()
    }

    fn metrics(window: &[Event<'_>]) -> Option<Value> {
        let model = window
            .iter()
            .rev()
            .find(|event| !event.model.is_empty())
            .map_or("", |event| event.model);
        let raw = window
            .iter()
            .try_fold(0i64, |total, event| total.checked_add(event.raw))?;
        let reasoning = window
            .iter()
            .try_fold(0i64, |total, event| total.checked_add(event.reasoning))?;
        let weight = if window.is_empty() {
            json!(0)
        } else {
            let PythonValue::Number(Number::Float(sum)) =
                PythonSum::sum(window.iter().map(|event| &event.weight))?
            else {
                return None;
            };
            if !sum.is_finite() {
                return None;
            }
            json!(sum)
        };
        Some(json!({
            "turns": window.len(), "event_model": model, "weighted_tokens": weight,
            "raw_tokens": raw, "reasoning_tokens": reasoning,
        }))
    }
}
