use super::*;
use sha2::{Digest, Sha256};

#[test]
fn every_unicode_scalar_matches_builder_python() {
    assert!(!UNICODE_VERSION.is_empty());
    let mut digest = Sha256::new();
    for character in (0..=0x10ffff).filter_map(char::from_u32) {
        digest.update(PythonText::repr(&character.to_string()).as_bytes());
        digest.update(b"\n");
        digest.update([
            u8::from(PythonText::printable(character)),
            u8::from(PythonText::decimal(character)),
            u8::from(PythonText::whitespace(character)),
        ]);
    }
    assert_eq!(
        format!("{:x}", digest.finalize()),
        SCALAR_GOLDEN_SHA256,
        "builder Unicode {UNICODE_VERSION}"
    );
}

#[test]
fn quote_choice_and_multicharacter_escaping() {
    for (text, expected) in [
        ("", "''"),
        ("it's", "\"it's\""),
        ("\"quoted\"", "'\"quoted\"'"),
        ("'\"", "'\\'\"'"),
        ("\\\n\t\r\0", "'\\\\\\n\\t\\r\\x00'"),
        ("é한😀", "'é한😀'"),
        ("\u{a0}\u{200b}\u{10ffff}", "'\\xa0\\u200b\\U0010ffff'"),
    ] {
        assert_eq!(PythonText::repr(text), expected);
    }
}

#[test]
fn unicode_categories_keep_python_distinctions() {
    assert!(PythonText::decimal('٩'));
    assert!(!PythonText::decimal('²'));
    assert!(PythonText::whitespace('\u{1c}'));
    assert!(!PythonText::whitespace('\u{200b}'));
    assert!(!PythonText::printable('\u{a0}'));
    assert!(PythonText::printable(' '));
}
