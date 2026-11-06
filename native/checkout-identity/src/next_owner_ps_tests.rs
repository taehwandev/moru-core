use super::*;

#[test]
fn ps_integer_uses_python_whitespace_digits_and_underscores() {
    for (text, expected) in [
        ("", 0),
        ("\r\n\u{1c}", 0),
        ("\u{85}+٤_２\r\n", 42),
        ("-1", -1),
        ("00042", 42),
        ("+", 0),
        ("1__2", 0),
        ("1_", 0),
        ("_1", 0),
        ("4\n2", 0),
        ("²", 0),
    ] {
        assert_eq!(
            PsParent::decode(text.as_bytes(), b""),
            Some(expected),
            "{text:?}"
        );
    }
    assert_eq!(PsParent::decode(b"42", b"\xff"), Some(0));
    assert_eq!(PsParent::decode(b"\xff", b""), Some(0));
    assert_eq!(
        PsParent::decode(b"9223372036854775807", b""),
        Some(i64::MAX)
    );
    assert_eq!(PsParent::decode(b"9223372036854775808", b""), None);
    assert_eq!(PsParent::decode(b"-9223372036854775809", b""), None);
}

#[test]
fn nonzero_exit_still_has_a_parseable_parent() {
    let (stdout, stderr, success) = capture_raw(
        Command::new("/bin/sh").args(["-c", "printf '42\\r\\n'; exit 7"]),
        Duration::from_secs(1),
    )
    .unwrap()
    .unwrap();
    assert!(!success);
    assert_eq!(PsParent::decode(&stdout, &stderr), Some(42));
}
