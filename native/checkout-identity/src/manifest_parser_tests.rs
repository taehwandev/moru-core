use super::*;
#[test]
fn syntax_errors_are_invalid_not_unsupported() {
    for source in [
        "",
        "{",
        "[",
        "[1,]",
        "{\"a\":}",
        "{\"a\" 1}",
        "[1 2]",
        "true false",
        "01",
        ".1",
        "1e+",
        "nonsense",
        "\"\\q\"",
        "\"\\u12xz\"",
        "\"\\u123\"",
        "\"raw\ntext\"",
        "\"unterminated",
        "\u{feff}{}",
        r#""\ud800\uZZZZ""#,
        r#""\udfff\q""#,
    ] {
        assert!(
            matches!(
                ManifestParser::outcome_with_limit(source, 0),
                ParseOutcome::Invalid
            ),
            "{source:?}"
        );
    }
    for source in [r#""\ud800""#, r#""\udfff""#, r#""\ud800\u1234""#] {
        assert!(
            matches!(
                ManifestParser::outcome_with_limit(source, 0),
                ParseOutcome::Unsupported
            ),
            "{source:?}"
        );
    }
}
#[test]
fn digit_limit_and_depth_failures_remain_distinct() {
    assert!(matches!(
        ManifestParser::outcome_with_limit("9999", 3),
        ParseOutcome::Invalid
    ));
    let deep = format!("{}0{}", "[".repeat(129), "]".repeat(129));
    assert!(matches!(
        ManifestParser::outcome_with_limit(&deep, 0),
        ParseOutcome::Unsupported
    ));
    for source in [
        r#""\u0000\n\t\r\b\f\/\\\"""#,
        r#""\ud83d\ude00""#,
        r#"{"\u0061":1}"#,
    ] {
        assert!(
            matches!(
                ManifestParser::outcome_with_limit(source, 0),
                ParseOutcome::Value(_)
            ),
            "{source:?}"
        );
    }
}
use crate::python_json::PythonJson;
fn text(source: &str) -> String {
    PythonJson::string(&ManifestParser::with_limit(source, 0).unwrap())
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
        assert!(PythonJson::truthy(&value));
        let Value::Number(number) = value else {
            panic!("number expected")
        };
        assert!(!number.equals_u64(1));
    }
    assert!(!PythonJson::truthy(
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
