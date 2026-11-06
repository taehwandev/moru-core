use super::*;
#[test]
fn scalar_errors_preserve_unicode_positions_and_prefix_consumption() {
    for (text, expected) in [
        ("", "Expecting value: line 1 column 1 (char 0)"),
        ("-", "Expecting value: line 1 column 1 (char 0)"),
        ("1.", "Extra data: line 1 column 2 (char 1)"),
        ("1e+", "Extra data: line 1 column 2 (char 1)"),
        ("[1.]", "Expecting ',' delimiter: line 1 column 3 (char 2)"),
        (
            "\u{feff}{}",
            "Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)",
        ),
        ("\"한😀\\q\"", "Invalid \\escape: line 1 column 4 (char 3)"),
        (
            "\"é\\u12z4\"",
            "Invalid \\uXXXX escape: line 1 column 4 (char 3)",
        ),
        (
            "\"a\\",
            "Unterminated string starting at: line 1 column 1 (char 0)",
        ),
        ("{\"é\":1}\n😀", "Extra data: line 2 column 1 (char 8)"),
        ("[\n\"é\",\n?]", "Expecting value: line 3 column 1 (char 7)"),
        (
            "\"a\n\"",
            "Invalid control character at: line 1 column 3 (char 2)",
        ),
    ] {
        assert_eq!(
            ManifestParser::error(text).as_deref(),
            Some(expected),
            "{text}"
        );
    }
}
#[test]
fn object_array_trailing_comma_is_bound_to_builder() {
    for (text, array, old_message, old_position, new_position) in [
        ("[1,]", true, "Expecting value", 3, 2),
        (
            "{\"a\":1,}",
            false,
            "Expecting property name enclosed in double quotes",
            7,
            6,
        ),
    ] {
        let (message, position) = if JsonDiagnostic::trailing(array) {
            (
                format!(
                    "Illegal trailing comma before end of {}",
                    if array { "array" } else { "object" }
                ),
                new_position,
            )
        } else {
            (old_message.into(), old_position)
        };
        assert_eq!(
            ManifestParser::error(text),
            Some(JsonDiagnostic::syntax(text, position, &message))
        );
    }
}
#[test]
fn unsupported_surrogates_depth_and_valid_values_have_no_diagnostic() {
    for text in ["null", "NaN", "\"\\ud800\"", "[1.0]"] {
        assert!(ManifestParser::error(text).is_none());
    }
    let deep = format!("{}0{}", "[".repeat(130), "]".repeat(130));
    assert!(ManifestParser::error(&deep).is_none());
    assert!(matches!(
        ManifestParser::parse_outcome("1e+"),
        ParseOutcome::Invalid
    ));
}

#[test]
fn conversion_digit_limit_precedes_later_syntax() {
    let limit = ManifestParser::limit().unwrap();
    if limit == 0 {
        return;
    }
    let number = "1".repeat(limit + 1);
    let expected = JsonDiagnostic::digits(limit, limit + 1).unwrap();
    for source in [number.clone(), format!("{number}x"), format!("[{number},]")] {
        assert_eq!(ManifestParser::error(&source), Some(expected.clone()));
        assert!(matches!(
            ManifestParser::parse_outcome(&source),
            ParseOutcome::Invalid
        ));
    }
}
