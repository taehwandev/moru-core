use super::*;
#[test]
fn nested_str_and_repr_share_one_python_contract() {
    let value = PythonJson::parse(
        r#"{"b":0,"a":[true,false,null,"é'\"",NaN,Infinity],"b":18446744073709551616}"#,
    )
    .unwrap();
    assert_eq!(
        PythonJson::string(&value),
        "{'b': 18446744073709551616, 'a': [True, False, None, 'é\\'\"', nan, inf]}"
    );
    assert_eq!(
        PythonJson::string(&PythonJson::parse(r#""plain""#).unwrap()),
        "plain"
    );
    assert_eq!(
        PythonJson::repr(&PythonJson::parse(r#""plain""#).unwrap()),
        "'plain'"
    );
}
#[test]
fn integers_and_floats_preserve_conversion_exceptions() {
    let huge = "9".repeat(400);
    let Value::Number(integer) = PythonJson::parse(&huge).unwrap() else {
        panic!("number expected")
    };
    assert_eq!(integer.text(), huge);
    assert!(integer.truthy());
    assert!(integer.as_float().is_none());
    let Value::Number(float) = PythonJson::parse("1e400").unwrap() else {
        panic!("number expected")
    };
    assert_eq!(float.as_float(), Some(f64::INFINITY));
    let Value::Number(integer) = PythonJson::parse("18446744073709551616").unwrap() else {
        panic!("number expected")
    };
    assert_eq!(integer.as_float(), Some(18446744073709551616.0));
}
#[test]
fn float_json_uses_python_decimal_ties_and_exponents() {
    let value =
        PythonJson::parse("[1466481018931781.25,-1466481018931781.25,1e-7,1e20,5e-324,-0.0]")
            .unwrap();
    assert_eq!(
        PythonJson::render(&value, false, false).unwrap(),
        "[1466481018931781.2, -1466481018931781.2, 1e-07, 1e+20, 5e-324, -0.0]"
    );
}
#[test]
fn truth_and_parser_declines_remain_explicit() {
    for text in ["false", "null", "0", "-0", "-0.0", "[]", "{}", r#""""#] {
        assert!(!PythonJson::truthy(&PythonJson::parse(text).unwrap()));
    }
    for text in ["NaN", "Infinity", "[false]", r#"{"x":null}"#] {
        assert!(PythonJson::truthy(&PythonJson::parse(text).unwrap()));
    }
    assert!(PythonJson::parse(r#""\ud800""#).is_none());
    assert!(PythonJson::parse("{").is_none());
}
