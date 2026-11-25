//! owner: pure loop candidate verdict; allowed imports: typed JSON and arithmetic;
//! forbidden imports: paths, subprocesses, state mutations and authority;
//! callers/tests: candidate transactions via completion transport, loop parity.
use serde_json::{json, Value};

pub(super) struct LoopVerdict;

impl LoopVerdict {
    pub(super) fn decide(request: &Value) -> Option<Value> {
        let timely = request.get("timely")?.as_bool()?;
        let regression = request.get("regression")?.as_bool()?;
        let goal = request.get("goal")?.as_bool()?;
        let reached = timely && regression && goal;
        let metric = request.get("metric")?;
        let improves = if metric.is_null() {
            reached
        } else {
            let direction = match metric.get("direction")?.as_str()? {
                "max" => 1.0,
                "min" => -1.0,
                _ => return None,
            };
            let threshold = Self::number(metric.get("min_delta")?)?;
            if threshold <= 0.0 {
                return None;
            }
            let value = Self::number(request.get("value")?)?;
            let baseline = Self::number(request.get("baseline")?)?;
            direction * (value - baseline) >= threshold
        };
        Some(json!({"goal": reached, "improves": improves}))
    }

    fn number(value: &Value) -> Option<f64> {
        let value = value.as_number()?;
        // Keep even a subtraction of two integer operands within an exact
        // binary64 range. Larger integers use Python's exact arithmetic.
        if !value.is_f64() && value.as_i64()?.unsigned_abs() > (1 << 52) {
            return None;
        }
        value.as_f64().filter(|value| value.is_finite())
    }
}
