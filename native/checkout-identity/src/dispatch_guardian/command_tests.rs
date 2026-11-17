use super::*;
use std::io::Cursor;

#[test]
fn bounded_newline_ingress_distinguishes_eof_invalid_and_valid_json() {
    for raw in [b"".as_slice(), b"{}", b"{}\r"] {
        assert!(DispatchGuardian::message(Cursor::new(raw))
            .unwrap()
            .is_none());
    }
    assert!(DispatchGuardian::message(Cursor::new(b"{\n")).is_err());
    assert!(DispatchGuardian::message(Cursor::new(b"\xff\n")).is_err());
    let mut exact = vec![b' '; LIMIT - 3];
    exact.extend_from_slice(b"{}\n");
    assert!(DispatchGuardian::message(Cursor::new(&exact))
        .unwrap()
        .is_some());
    exact.insert(0, b' ');
    assert!(DispatchGuardian::message(Cursor::new(exact))
        .unwrap()
        .is_none());
}

#[test]
fn canonical_request_keeps_argument_and_environment_order_without_coercion() {
    let value =
        PythonJson::parse(r#"{"command":["/bin/echo","한글","", "a b"],"env":{"B":"2","A":"1"}}"#)
            .unwrap();
    let (command, environment) = DispatchGuardian::request(&value).unwrap();
    assert_eq!(command, vec!["/bin/echo", "한글", "", "a b"]);
    assert_eq!(
        environment,
        vec![("B".into(), "2".into()), ("A".into(), "1".into())]
    );
    for raw in [
        r#"{"command":[],"env":{}}"#,
        r#"{"command":[1],"env":{}}"#,
        r#"{"command":["a\u0000b"],"env":{}}"#,
        r#"{"command":["a"],"env":{"X":1}}"#,
        r#"{"command":["a"],"env":{"X=Y":"z"}}"#,
        r#"{"command":["a"],"env":{"X":"\u0000"}}"#,
        r#"{"command":["a"],"env":{},"unknown":1}"#,
        r#"{"command":["a"]}"#,
    ] {
        assert!(
            DispatchGuardian::request(&PythonJson::parse(raw).unwrap()).is_err(),
            "{raw}"
        );
    }
}

#[test]
fn exec_search_preserves_empty_relative_and_raw_path_components_without_shell() {
    let list = DispatchGuardian::exec_candidates(b"worker", b":relative:/bin/").unwrap();
    assert_eq!(
        list.iter().map(|path| path.as_bytes()).collect::<Vec<_>>(),
        vec![b"worker".as_slice(), b"relative/worker", b"/bin/worker"]
    );
    let list = DispatchGuardian::exec_candidates(b"./worker", b"/ignored").unwrap();
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].as_bytes(), b"./worker");
    assert!(DispatchGuardian::exec_candidates(b"worker", b"bad\0path").is_err());
}
