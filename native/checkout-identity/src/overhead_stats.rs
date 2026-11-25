//! owner: OverheadStats; allowed imports: shared numeric owners, std/JSON;
//! forbidden imports: I/O and Python processes; callers/tests: report aggregates/timings;
//! verification: exact means, percentiles, sum profiles and decimal rounding parity.
use crate::{
    python_json::{Number, Object, Value},
    python_mean::PythonMean,
    python_sum::PythonSum,
};
pub(super) struct OverheadStats;
impl OverheadStats {
    pub(super) fn summarize(values: &[Value]) -> Option<Value> {
        let numbers: Vec<_> = values
            .iter()
            .filter(|v| !matches!(v, Value::Null))
            .collect();
        let mut summary = Object::new();
        summary.insert(
            "n".into(),
            Value::Number(Number::Integer(numbers.len().to_string())),
        );
        if numbers.is_empty() {
            return Some(Value::Object(summary));
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
                Value::Number(Number::Integer((sum / count).to_string()))
            } else {
                Self::rounded(sum as f64 / count as f64)?
            };
            (mean, total)
        } else {
            let mean = floats
                .iter()
                .copied()
                .filter(|value| value.is_infinite())
                .reduce(|left, right| left + right);
            let Value::Number(sum) = total else {
                return None;
            };
            (
                Self::rounded(match mean {
                    Some(nonfinite) => nonfinite,
                    None => PythonMean::calculate(&floats)?,
                })?,
                Self::rounded(sum.as_float()?)?,
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
        summary.insert("median".into(), Self::percentile(&sorted, 0.5)?);
        summary.insert("p90".into(), Self::percentile(&sorted, 0.9)?);
        summary.insert("mean".into(), mean);
        summary.insert("sum".into(), sum);
        Some(Value::Object(summary))
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
            // NaN comparisons are unordered; Python's sort can depend on the
            // input run structure. Keep raw NaN samples on the reference path.
            Value::Number(Number::Float(v)) if !v.is_nan() => Some(*v),
            _ => None,
        }
    }
    pub(super) fn rounded(value: f64) -> Option<Value> {
        if !value.is_finite() {
            return Some(Value::Number(Number::Float(value)));
        }
        // Fixed precision formats the binary value directly with ties-to-even,
        // unlike multiplying by 100, which introduces an extra rounding step.
        let rounded: f64 = format!("{value:.2}").parse().ok()?;
        rounded
            .is_finite()
            .then_some(Value::Number(Number::Float(rounded)))
    }
    fn percentile(sorted: &[&Value], quantile: f64) -> Option<Value> {
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
