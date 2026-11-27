//! Shared Figma decimal rounding for prototype durations and layout metrics.
use crate::python_json::Number;

pub(super) fn round_number(value: &Number) -> Option<Number> {
    let Number::Float(value) = value else {
        return Some(value.clone());
    };
    if !value.is_finite() || value.abs() >= 9_007_199_254_740_992.0 {
        return None;
    }
    let integer = value.round_ties_even();
    if (value - integer).abs() < 0.001 {
        return Some(Number::Integer((integer as i64).to_string()));
    }
    // Round the binary input directly instead of rounding an intermediate scaled float.
    Some(Number::Float(format!("{value:.2}").parse().ok()?))
}
