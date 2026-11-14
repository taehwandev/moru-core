use super::*;

#[test]
fn normalization_preserves_lowercase_rather_than_casefold_and_punctuation_order() {
    for (text, expected) in [
        ("Straße STRASSE", "straße strasse"),
        ("İ I i", "i i i"),
        ("A-B A B foo_bar", "ab a b foo_bar"),
        ("  한글! 본문? ", "한글 본문"),
        ("e\u{301} É", "e é"),
        ("!@#$%^&*", ""),
        ("Ⅰ²０", "ⅰ²０"),
    ] {
        assert_eq!(MemoryTerms::normalize(text), expected);
    }
}

#[test]
fn normalization_observes_final_sigma_before_punctuation_and_combining_mark_removal() {
    for (text, expected) in [
        ("ΟΣ", "ος"),
        ("ΟΣΑ", "οσα"),
        ("Σ", "σ"),
        ("AΣ\u{301}", "aς"),
        ("AΣ\u{301}B", "aσb"),
        ("AΣ'", "aς"),
        ("AΣ'B", "aσb"),
        ("AΣ B", "aς b"),
        ("AΣ\u{200d}B", "aσb"),
        ("AᵃΣ", "aᵃς"),
        ("ᵃΣ", "ᵃσ"),
    ] {
        assert_eq!(MemoryTerms::normalize(text), expected, "{text}");
    }
}

#[test]
fn normalization_uses_python_control_and_unicode_whitespace() {
    assert_eq!(
        MemoryTerms::normalize(" \tA\u{1c}B\u{1d}C\u{1e}D\u{1f}E\u{85}F\u{a0}G\u{2028}H\u{3000} "),
        "a b c d e f g h"
    );
    assert_eq!(MemoryTerms::normalize("A\u{200b}B\0C"), "abc");
    assert_eq!(MemoryTerms::normalize("A !\t- B"), "a b");
}
