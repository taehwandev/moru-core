//! owner: CoverageFloat; allowed imports: std/shared Number, builder sum constants;
//! forbidden imports: I/O; callers/tests: CoverageSum; verification: CPython profile cases.
use crate::python_json::Number;
include!(concat!(env!("OUT_DIR"), "/figma_contract.rs"));
pub(super) struct CoverageFloat {
    high: f64,
    low: f64,
    fast: bool,
}
impl CoverageFloat {
    pub(super) fn new(integer: &str, value: f64, fast: bool) -> Option<Self> {
        let previous = Number::Integer(integer.into()).as_float()?;
        Some(Self {
            high: previous + value,
            low: 0.0,
            fast,
        })
    }
    pub(super) fn fits_long(text: &str) -> bool {
        let bound = 1i128 << (SUM_LONG_BITS - 1);
        text.parse::<i128>()
            .is_ok_and(|value| (-bound..bound).contains(&value))
    }
    pub(super) fn add(&mut self, number: &Number) -> Option<()> {
        let value = number.as_float()?;
        if !self.fast || SUM_PROFILE == "sequential" {
            self.high += value;
        } else if SUM_PROFILE == "float_compensated" && matches!(number, Number::Integer(_)) {
            let Number::Integer(text) = number else {
                unreachable!()
            };
            if Self::fits_long(text) {
                self.high += value;
            } else {
                self.high = self.finish() + value;
                self.low = 0.0;
                self.fast = false;
            }
        } else {
            // CPython's Neumaier compensation, preserving evaluation order.
            let total = self.high + value;
            self.low += if self.high.abs() >= value.abs() {
                (self.high - total) + value
            } else {
                (value - total) + self.high
            };
            self.high = total;
        }
        Some(())
    }
    pub(super) fn finish(&self) -> f64 {
        if self.low != 0.0 && self.low.is_finite() {
            self.high + self.low
        } else {
            self.high
        }
    }
}
