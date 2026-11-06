use super::*;
use crate::python_json::PythonJson;

#[test]
fn proc_fields_use_last_parenthesis_and_python_whitespace() {
    assert_eq!(
        ProcessOwner::parent_field("12 (runtime ) helper) S\r\n٤_٢\u{85}0"),
        Some("42".into())
    );
    assert_eq!(ProcessOwner::parent_field("S +42"), Some("+42".into()));
    for text in ["12 (p) S _1", "12 (p) S 1__2", "12 (p) S +", "12 (p) S", ""] {
        assert!(ProcessOwner::parent_field(text).is_none(), "{text}");
    }
    let fields = (0..21)
        .map(|n| n.to_string())
        .collect::<Vec<_>>()
        .join("\u{1c}");
    assert_eq!(ProcessOwner::token(&format!("42 (p)) {fields}")), "19");
    assert_eq!(ProcessOwner::token("42 (p) S 1"), "");
    assert_eq!(
        ProcessOwner::token(&String::from_utf8_lossy(b"42 (bad\xff) S 1")),
        ""
    );
}

#[test]
fn parent_one_anchors_leader_and_unavailable_parent_has_no_owner() {
    assert_eq!(ProcessOwner::anchor(42, 1), Some(42));
    assert_eq!(ProcessOwner::anchor(42, 9), Some(9));
    assert_eq!(ProcessOwner::anchor(42, 0), None);
    assert_eq!(ProcessOwner::anchor(42, -1), None);
}

#[test]
fn full_dictionary_equality_does_not_accept_partial_owner() {
    let owner = ProcessOwner {
        pid: 42,
        start_token: "token".into(),
    };
    for text in [
        r#"{"pid":42,"start_token":"token"}"#,
        r#"{"pid":42.0,"start_token":"token"}"#,
    ] {
        assert!(owner.matches(Some(&PythonJson::parse(text).unwrap())));
    }
    for text in [
        r#"{"pid":"42","start_token":"token"}"#,
        r#"{"pid":42,"start_token":"other"}"#,
        r#"{"pid":42,"start_token":"token","extra":false}"#,
        r#"{"pid":42}"#,
        "null",
        r#"{"pid":9007199254740993,"start_token":"token"}"#,
    ] {
        assert!(
            !owner.matches(Some(&PythonJson::parse(text).unwrap())),
            "{text}"
        );
    }
    let owner = ProcessOwner {
        pid: 1,
        start_token: String::new(),
    };
    assert!(owner.matches(Some(
        &PythonJson::parse(r#"{"pid":true,"start_token":""}"#).unwrap()
    )));
}
