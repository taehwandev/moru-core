use super::*;
macro_rules! json { ($($t:tt)*) => { Value::from(serde_json::json!($($t)*)) }; }
#[test]
fn float_spelling() {
    for (v, s) in [
        (1e-5, "1e-05"),
        (1e-4, "0.0001"),
        (1e16, "1e+16"),
        (1e15, "1000000000000000.0"),
        (-0.0, "-0.0"),
    ] {
        assert_eq!(super::super::number::ManifestNumber::float(v), s);
    }
}
#[test]
fn truth_and_repr() {
    assert!(!ManifestValidation::truthy(&json!([])));
    assert!(ManifestValidation::truthy(&json!([false])));
    assert_eq!(
        ManifestValidation::string(&json!({"a":[true,null,"x"]})).unwrap(),
        "{'a': [True, None, 'x']}"
    );
}
#[test]
fn ordered_failures() {
    let f = ManifestValidation::failures(
        &json!({"schema_version":true,"repositories":{"z":null},"skills":[null]}),
        Path::new("."),
    )
    .unwrap();
    assert!(f[0].starts_with("repository z"));
    assert_eq!(f.last().unwrap(), "every skill entry must be an object");
    assert_eq!(f.len(), 6);
}
#[test]
fn schema_first() {
    assert_eq!(
        ManifestValidation::failures(
            &json!({"schema_version":2,"repositories":{"z":null}}),
            Path::new(".")
        )
        .unwrap(),
        vec![ManifestValidation::schema()]
    );
}
