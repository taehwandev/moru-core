use super::super::validation::ManifestValidation;
use super::*;
fn text(source: &str) -> String {
    ManifestValidation::string(&ManifestParser::with_limit(source, 0).unwrap()).unwrap()
}
#[test]
fn arbitrary_integers_and_signed_zero() {
    for source in [
        "18446744073709551616",
        "-9223372036854775809",
        "99999999999999999999999999999999999999999999999999999999999999999",
    ] {
        assert_eq!(text(source), source);
    }
    assert_eq!(text("-0"), "0");
    assert_eq!(text("-0.0"), "-0.0");
    assert_eq!(text("-0e0"), "-0.0");
    assert_eq!(text("[-0, -0.0, 1, 1.0]"), "[0, -0.0, 1, 1.0]");
}
#[test]
fn nonfinite_and_overflow_are_python_values() {
    assert_eq!(
        text("[NaN, Infinity, -Infinity, 1e999, -1e999, 1e-999, -1e-999]"),
        "[nan, inf, -inf, inf, -inf, 0.0, -0.0]"
    );
    for source in ["NaN", "Infinity", "-Infinity"] {
        let value = ManifestParser::with_limit(source, 0).unwrap();
        assert!(ManifestValidation::truthy(&value));
        let Value::Number(number) = value else {
            panic!("number expected")
        };
        assert!(!number.equals_u64(1));
    }
    assert!(!ManifestValidation::truthy(
        &ManifestParser::with_limit("-0", 0).unwrap()
    ));
}
#[test]
fn objects_keep_first_position_and_last_value() {
    assert_eq!(
        text(r#"{"z":0,"a":1,"z":18446744073709551616,"b":NaN}"#),
        "{'z': 18446744073709551616, 'a': 1, 'b': nan}"
    );
    assert_eq!(
        text(r#"{"é":"한😀","\u00e9":"replacement"}"#),
        "{'é': 'replacement'}"
    );
}
#[test]
fn malformed_lexemes_decline_before_validation() {
    for source in [
        "",
        "01",
        "-01",
        "+1",
        ".1",
        "1.",
        "1e",
        "1e+",
        "--1",
        "nan",
        "inf",
        "-NaN",
        "Infinity0",
        "[1,]",
        "{\"a\":1,}",
        "[1 2]",
        "true false",
        "\u{a0}1",
        "\"raw\nnewline\"",
        "\"\\ud800\"",
        "\"\\udfff\"",
        "\"\\q\"",
    ] {
        assert!(
            ManifestParser::with_limit(source, 0).is_none(),
            "{source:?}"
        );
    }
    assert_eq!(text(r#""\ud83d\ude00""#), "😀");
}
#[test]
fn limits_are_pre_effect_declines() {
    assert!(ManifestParser::with_limit("999", 3).is_some());
    assert!(ManifestParser::with_limit("-999", 3).is_some());
    assert!(ManifestParser::with_limit("9999", 3).is_none());
    assert!(ManifestParser::with_limit("9999.0", 3).is_some());
    let deep = format!("{}0{}", "[".repeat(129), "]".repeat(129));
    assert!(ManifestParser::with_limit(&deep, 0).is_none());
}
