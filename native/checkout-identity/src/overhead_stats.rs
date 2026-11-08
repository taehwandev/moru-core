//! owner: OverheadStats; allowed imports: shared numeric owners, std/JSON;
//! forbidden imports: I/O and Python processes; callers/tests: report aggregates/timings;
//! verification: exact means, percentiles, sum profiles and decimal rounding parity.
use crate::{
    python_json::{Number, Value},
    python_mean::PythonMean,
    python_sum::PythonSum,
};
use serde_json::{json, Value as Json};

pub(super) struct OverheadStats;
impl OverheadStats {
    pub(super) fn summarize(values: &[Value]) -> Option<Json> {
        let numbers: Vec<_> = values
            .iter()
            .filter(|v| !matches!(v, Value::Null))
            .collect();
        if numbers.is_empty() {
            return Some(json!({"n":0}));
        }
        let floats = numbers
            .iter()
            .map(|v| Self::float(v))
            .collect::<Option<Vec<_>>>()?;
        let integer = numbers
            .iter()
            .all(|v| matches!(v, Value::Number(Number::Integer(_))));
        let total = PythonSum::sum(numbers.iter().copied())?;
        let (mean, sum) = if integer {
            let sum = Self::integer(&total)?;
            let count = numbers.len() as i64;
            let mean = if sum % count == 0 {
                json!(sum / count)
            } else {
                Self::rounded(sum as f64 / count as f64)?
            };
            (mean, json!(sum))
        } else {
            (
                Self::rounded(PythonMean::calculate(&floats)?)?,
                Self::rounded(Self::float(&total)?)?,
            )
        };
        let mut sorted = numbers;
        // Stable equality includes +0/-0, preserving Python's sorted input order.
        sorted.sort_by(|a, b| {
            Self::float(a)
                .unwrap()
                .partial_cmp(&Self::float(b).unwrap())
                .unwrap()
        });
        Some(
            json!({"n":sorted.len(),"median":Self::percentile(&sorted,0.5)?,
            "p90":Self::percentile(&sorted,0.9)?,"mean":mean,"sum":sum}),
        )
    }
    pub(super) fn integer(value: &Value) -> Option<i64> {
        let Value::Number(Number::Integer(text)) = value else {
            return None;
        };
        // These integers and every accumulated total have an exact f64 representation.
        text.parse::<i64>()
            .ok()
            .filter(|v| v.unsigned_abs() <= (1u64 << 53))
    }
    pub(super) fn float(value: &Value) -> Option<f64> {
        match value {
            Value::Number(Number::Integer(_)) => Self::integer(value).map(|v| v as f64),
            Value::Number(Number::Float(v)) if v.is_finite() => Some(*v),
            _ => None,
        }
    }
    pub(super) fn rounded(value: f64) -> Option<Json> {
        if !value.is_finite() {
            return None;
        }
        // Fixed precision formats the binary value directly with ties-to-even,
        // unlike multiplying by 100, which introduces an extra rounding step.
        let rounded: f64 = format!("{value:.2}").parse().ok()?;
        rounded.is_finite().then(|| json!(rounded))
    }
    fn percentile(sorted: &[&Value], quantile: f64) -> Option<Json> {
        let position = (sorted.len() - 1) as f64 * quantile;
        let low = position as usize;
        let high = (low + 1).min(sorted.len() - 1);
        let delta = match (sorted[high], sorted[low]) {
            (Value::Number(Number::Integer(_)), Value::Number(Number::Integer(_))) => {
                (Self::integer(sorted[high])? - Self::integer(sorted[low])?) as f64
            }
            (a, b) => Self::float(a)? - Self::float(b)?,
        };
        Self::rounded(Self::float(sorted[low])? + delta * (position - low as f64))
    }
}
