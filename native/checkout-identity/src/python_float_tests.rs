use super::*;
#[test]
fn decimal_digits_underscores_and_whitespace() {
    for (text, value) in [
        ("٣٠٠", 300.0),
        ("𝟛𝟘𝟘", 300.0),
        ("１０_０.５", 100.5),
        ("\u{85}\u{a0} ١_٢.٥e+١\u{2003}", 125.0),
        ("\t\n\x0b\x0c 1. \r", 1.0),
        ("1.e2", 100.0),
        (".٢e-١", 0.02),
        ("1e3_0", 1e30),
    ] {
        assert_eq!(PythonFloat::parse(text), Some(value), "{text:?}");
    }
    for text in [
        "",
        "²",
        "１２٫５",
        "1__0",
        "_1",
        "1_",
        "1_.0",
        "1._0",
        "1e_2",
        "1e+_2",
        "1 2",
        "\u{1c}1",
        "1\u{1f}",
        "\u{a0}\u{1c}1",
        "nan_",
        "infinite",
        "+-inf",
        "0x1",
        "\0",
        "1\u{200b}",
    ] {
        assert!(PythonFloat::parse(text).is_none(), "{text:?}");
    }
}
#[test]
fn nonfinite_and_signed_zero_are_values() {
    for text in ["nan", "NaN", "+nan", "-NAN"] {
        assert!(PythonFloat::parse(text).unwrap().is_nan());
    }
    for text in ["inf", "INFINITY", "+Inf", "1e999"] {
        assert_eq!(PythonFloat::parse(text), Some(f64::INFINITY));
    }
    for text in ["-Inf", "-INFINITY", "-1e999"] {
        assert_eq!(PythonFloat::parse(text), Some(f64::NEG_INFINITY));
    }
    for text in ["-0", "-٠.٠", "-1e-999"] {
        assert!(PythonFloat::parse(text).unwrap().is_sign_negative());
    }
}
