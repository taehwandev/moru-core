//! owner: pure loop budget policy; allowed imports: JSON values and arithmetic;
//! forbidden imports: clocks, state files, subprocesses, ownership or writes;
//! callers/tests: loop contract through completion transport, native loop parity.
use serde_json::{json, Value};

pub(super) struct LoopBudget;

impl LoopBudget {
    pub(super) fn decide(request: &Value) -> Option<Value> {
        let now = Self::seconds(request.get("now")?)?;
        let deadline = Self::seconds(request.get("deadline")?)?;
        let new_attempt = request.get("new_attempt")?.as_bool()?;
        let iterations = request.get("iterations")?.as_u64()?;
        let iteration_limit = request.get("iteration_limit")?.as_u64()?;
        let used = request.get("used")?.as_u64()?;
        let call_limit = request.get("call_limit")?.as_u64()?;
        let calls = request.get("calls")?.as_u64()?;
        if !(1..=1000).contains(&iteration_limit)
            || !(1..=10000).contains(&call_limit)
            || iterations > iteration_limit
            || used > call_limit
            || calls > 10000
        {
            return None;
        }
        let decision = if now >= deadline
            || new_attempt && iterations == iteration_limit
            || (new_attempt || calls > 0) && used == call_limit
        {
            "exhausted"
        } else if calls > call_limit - used {
            "over_budget"
        } else {
            "allow"
        };
        Some(json!({"decision": decision}))
    }

    fn seconds(value: &Value) -> Option<f64> {
        let number = value.as_number()?;
        if !number.is_f64() && number.as_i64()?.unsigned_abs() > (1 << 53) {
            return None;
        }
        number.as_f64().filter(|value| value.is_finite())
    }
}
