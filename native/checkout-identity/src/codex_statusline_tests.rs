use super::CodexStatusLine as C;

#[test]
fn defaults_and_subtable_insertion_are_exact() {
    assert_eq!(C::merge("").1, "[tui]\nstatus_line = [\"model-with-reasoning\", \"current-dir\", \"five-hour-limit\", \"weekly-limit\"]\n");
    let text = "model = 'x'\n[tui.child]\nx = 2\n";
    let (status, result) = C::merge(text);
    assert_eq!(status, "changed");
    assert!(result.starts_with("model = 'x'\ntui.status_line = ["));
    assert!(result.ends_with("[tui.child]\nx = 2\n"));
}

#[test]
fn conflicts_and_malformed_arrays_remain_untouched() {
    for text in [
        "tui = {}\n",
        "[tui]\n[tui]\n",
        "[tui]\nstatus_line = 7\n",
        "[tui]\nstatus_line = [\"x\" 7]",
        "[tui]\nstatus_line = [\"\"\"x\"\"\"]",
        "[tui]\nstatus_line = [\"x\"]\nstatus_line = []",
    ] {
        assert_eq!(C::merge(text), ("missing", text.into()), "{text}");
    }
}

#[test]
fn comments_indentation_and_quote_escapes_are_preserved() {
    let text = "[tui]\nstatus_line = [\n  \"한글\\\"#]\" # keep\n]\n[other]\nx=7\n";
    assert_eq!(C::merge(text).1,
        "[tui]\nstatus_line = [\n  \"한글\\\"#]\", # keep\n  \"five-hour-limit\", \"weekly-limit\"\n]\n[other]\nx=7\n");
    assert_eq!(
        C::merge("[tui]\nstatus_line = ['five-hour-limit', 'weekly-limit']").0,
        "ok"
    );
}

#[test]
fn table_boundaries_and_unicode_spacing_match_python_rules() {
    assert_eq!(
        C::merge("[\u{1c}tui\u{1f}] # comment\nstatus_line =\u{1c}[]").1,
        "[\u{1c}tui\u{1f}] # comment\nstatus_line =\u{1c}[\"five-hour-limit\", \"weekly-limit\"]"
    );
    assert_eq!(C::headers("[tui]\r\n[other] # comment\r\n").len(), 1);
    assert_eq!(
        C::assignments("status_line_other=[]\n status_line \t= []", "status_line"),
        vec![
            "status_line_other=[]\n status_line \t= []"
                .rfind('=')
                .unwrap()
                + 1
        ]
    );
}
