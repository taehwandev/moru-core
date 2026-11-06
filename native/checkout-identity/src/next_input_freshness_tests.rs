use super::*;
#[test]
fn pathlib_root_spelling_is_preserved_before_snapshot_comparison() {
    for (raw, expected) in [
        ("", "."),
        ("./project", "project"),
        ("././project//a/./", "project/a"),
        ("///tmp//a", "/tmp/a"),
        ("//tmp//a", "//tmp/a"),
        ("a/../b", "a/../b"),
    ] {
        let value = Value::String(raw.into());
        assert_eq!(
            InputFreshness::path(Some(&value)).unwrap().to_str(),
            Some(expected)
        );
    }
    assert!(InputFreshness::path(Some(&Value::String("bad\0path".into()))).is_none());
}
