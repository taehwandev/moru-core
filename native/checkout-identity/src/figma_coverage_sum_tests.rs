use super::*;
use crate::python_json::PythonJson;
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
fn exact_float_sums_are_version_independent_others_defer() {
    assert_eq!(sum("[1,2.5,0.5]"), Some("4.0".into()));
    assert_eq!(sum("[-0.0]"), Some("0.0".into()));
    for text in [
        "[0.1,0.2]",
        "[Infinity]",
        "[NaN]",
        "[9007199254740993,1.0]",
        "[1e308,1e308]",
    ] {
        assert!(sum(text).is_none(), "{text}");
    }
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
