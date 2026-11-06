use super::*;
use crate::python_json::PythonJson;
mod profile {
    include!(concat!(env!("OUT_DIR"), "/figma_contract.rs"));
    pub(super) fn values() -> (&'static str, u32) {
        (SUM_PROFILE, SUM_LONG_BITS)
    }
}
fn sum(text: &str) -> Option<String> {
    let values = PythonJson::parse(text).unwrap();
    CoverageSum::sum(values.as_array().unwrap().iter()).map(|v| PythonJson::string(&v))
}
#[test]
fn arbitrary_integer_sum_and_cancellation_are_exact() {
    assert_eq!(
        sum("[999999999999999999999999999999,1]"),
        Some("1000000000000000000000000000000".into())
    );
    assert_eq!(
        sum("[999999999999999999999999999999,-999999999999999999999999999998]"),
        Some("1".into())
    );
    assert_eq!(sum("[-99,100,-5]"), Some("-4".into()));
    assert_eq!(sum("[true,false,null,\"2\"]"), Some("0".into()));
}
#[test]
fn float_nonfinite_and_rounded_conversions_are_supported() {
    assert_eq!(sum("[1,2.5,0.5]"), Some("4.0".into()));
    assert_eq!(sum("[-0.0]"), Some("0.0".into()));
    for (text, expected) in [
        ("[0.1,0.2]", "0.30000000000000004"),
        ("[Infinity]", "inf"),
        ("[NaN]", "nan"),
        ("[Infinity,-Infinity]", "nan"),
        ("[9007199254740993,1.0]", "9007199254740992.0"),
        ("[1e308,1e308]", "inf"),
    ] {
        assert_eq!(sum(text), Some(expected.into()), "{text}");
    }
    assert!(sum(&format!("[1{},1.0]", "0".repeat(400))).is_none());
}

#[test]
fn builder_bound_compensation_and_generic_transition_match_python() {
    let (sum_profile, sum_long_bits) = profile::values();
    assert_eq!(
        sum("[1e16,1.0,-1e16]"),
        Some(
            if sum_profile == "sequential" {
                "0.0"
            } else {
                "1.0"
            }
            .into()
        )
    );
    assert_eq!(
        sum("[1e16,1,-1e16]"),
        Some(
            if sum_profile == "all_compensated" {
                "1.0"
            } else {
                "0.0"
            }
            .into()
        )
    );
    let big = 1i128 << (sum_long_bits - 1);
    assert_eq!(
        sum(&format!("[{big},-{big},1e16,1.0,-1e16]")),
        Some("0.0".into())
    );
    assert_eq!(
        sum(&format!("[{},1,-{big},1e16,1.0,-1e16]", big - 1)),
        Some("0.0".into())
    );
}

#[test]
fn sum_must_preserve_python_output_digit_limit() {
    let limit: usize = env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().unwrap();
    if limit == 0 {
        return;
    }
    let values = [
        Value::Number(Number::Integer("9".repeat(limit))),
        Value::Number(Number::Integer("1".into())),
    ];
    assert!(CoverageSum::sum(values.iter()).is_none());
}
