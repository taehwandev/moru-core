use super::*;

fn binding_request(question: &str, context: &str) -> Value {
    json!({
        "unicode": MemoryTerms::version(),
        "question": question,
        "context": context,
    })
}

fn candidate_row(scope: &str, analysis: Option<(Option<&str>, Option<&str>)>) -> Value {
    let analysis_value = match analysis {
        None => Value::Null,
        Some((question, context)) => json!({
            "question": question,
            "context": context,
        }),
    };
    json!({
        "scope": scope,
        "analysis": analysis_value,
    })
}

fn candidates_request(scope: &str, question: &str, context: &str, records: Vec<Value>) -> Value {
    json!({
        "unicode": MemoryTerms::version(),
        "scope": scope,
        "binding": {
            "question": question,
            "context": context,
        },
        "records": records,
    })
}

#[test]
fn empty_binding_returns_null_and_partial_or_blank_inputs_report_invalid() {
    assert_eq!(
        MemoryAnalysis::evaluate("analysis-binding", &binding_request("", "")),
        Some(json!({ "binding": null }))
    );

    for (question, context) in [
        ("", "ctx"),
        ("question", ""),
        ("   ", "ctx"),
        ("question", "   "),
        ("   ", "   "),
        ("", "   "),
        ("   ", ""),
    ] {
        assert_eq!(
            MemoryAnalysis::evaluate("analysis-binding", &binding_request(question, context)),
            Some(json!({ "invalid": true })),
            "expected invalid for ({question:?}, {context:?})"
        );
    }
}

#[test]
fn edge_spaces_trim_while_preserving_case_negation_spacing_combining_and_key_order() {
    let payload = json!({
        "context": "   env=PROD  not_cached  e\u{0301}  🦀   ",
        "question": "  Why NOT use CacheV2?  ",
        "unicode": MemoryTerms::version(),
    });
    let result = MemoryAnalysis::evaluate("analysis-binding", &payload).expect("valid binding");
    assert_eq!(
        result,
        json!({
            "binding": {
                "question": "Why NOT use CacheV2?",
                "context": "env=PROD  not_cached  e\u{0301}  🦀",
            }
        })
    );
    let keys: Vec<&str> = result["binding"]
        .as_object()
        .expect("binding object")
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(keys, vec!["question", "context"]);
    assert_ne!(
        result["binding"]["context"],
        json!("env=PROD  not_cached  \u{00e9}  🦀")
    );
}

#[test]
fn original_300_and_301_character_limits_count_unicode_scalars_before_strip() {
    let ascii_300 = "a".repeat(300);
    let ascii_301 = "a".repeat(301);
    let astral_300 = "🦀".repeat(300);
    let astral_301 = "🦀".repeat(301);
    let padded_300 = format!("{}x", " ".repeat(299));
    let padded_301_left = format!("{}x", " ".repeat(300));
    let padded_301_right = format!("y{}", " ".repeat(300));

    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-binding",
            &binding_request(&ascii_300, &astral_300)
        ),
        Some(json!({
            "binding": {
                "question": ascii_300,
                "context": astral_300,
            }
        }))
    );
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-binding",
            &binding_request(&padded_300, &padded_300)
        ),
        Some(json!({
            "binding": {
                "question": "x",
                "context": "x",
            }
        }))
    );

    for bad in [&ascii_301, &astral_301, &padded_301_left, &padded_301_right] {
        assert_eq!(
            MemoryAnalysis::evaluate("analysis-binding", &binding_request(bad, "ok")),
            Some(json!({ "invalid": true }))
        );
        assert_eq!(
            MemoryAnalysis::evaluate("analysis-binding", &binding_request("ok", bad)),
            Some(json!({ "invalid": true }))
        );
    }
}

#[test]
fn controls_newlines_and_nonprintable_whitespace_reject_before_trim() {
    for ws in [
        '\n', '\r', '\t', '\u{0b}', '\u{0c}', '\u{1c}', '\u{85}', '\u{a0}', '\u{3000}',
    ] {
        assert!(PythonText::whitespace(ws));
        assert!(!PythonText::printable(ws));
    }

    for bad in [
        "\nquestion",
        "question\n",
        "\rquestion",
        "question\r\n",
        "\tquestion",
        "question\t",
        "\u{0b}question",
        "\u{0c}question",
        "\u{1c}question",
        "\u{85}question",
        "\u{a0}question",
        "question\u{a0}",
        "\u{2000}question",
        "\u{2028}question",
        "\u{2029}question",
        "\u{3000}question",
        "ques\0tion",
        "ques\u{200b}tion",
    ] {
        assert_eq!(
            MemoryAnalysis::evaluate("analysis-binding", &binding_request(bad, "valid")),
            Some(json!({ "invalid": true })),
            "expected invalid question for {bad:?}"
        );
        assert_eq!(
            MemoryAnalysis::evaluate("analysis-binding", &binding_request("valid", bad)),
            Some(json!({ "invalid": true })),
            "expected invalid context for {bad:?}"
        );
    }
}

#[test]
fn candidates_match_exact_scope_question_context_and_reject_near_misses() {
    let question = "Why NOT use e\u{0301}?";
    let context = "flag=1  mode=dev";
    let records = vec![
        candidate_row("task", Some((Some(question), Some(context)))),
        candidate_row("all", Some((Some(question), Some(context)))),
        candidate_row("other", Some((Some(question), Some(context)))),
        candidate_row(
            "task",
            Some((Some("why not use e\u{0301}?"), Some(context))),
        ),
        candidate_row("task", Some((Some("Why use e\u{0301}?"), Some(context)))),
        candidate_row("task", Some((Some(question), Some("flag=1 mode=dev")))),
        candidate_row(
            "task",
            Some((Some(" Why NOT use e\u{0301}? "), Some(context))),
        ),
        candidate_row("task", Some((Some("Why NOT use \u{00e9}?"), Some(context)))),
        candidate_row("task", Some((Some(question), Some("flag=1  mode=prod")))),
        candidate_row("task", Some((Some("Other?"), Some(context)))),
        candidate_row("task", Some((Some(question), Some(context)))),
    ];

    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", question, context, records.clone())
        ),
        Some(json!({ "indices": [0, 10] }))
    );
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("all", question, context, records.clone())
        ),
        Some(json!({ "indices": [1] }))
    );
    // Binding is not normalized inside analysis-candidates.
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", " Why NOT use e\u{0301}? ", context, records)
        ),
        Some(json!({ "indices": [6] }))
    );
}

#[test]
fn candidates_absent_analysis_and_null_fields_never_equal_strings() {
    let records = vec![
        candidate_row("task", None),
        candidate_row("task", Some((None, Some("ctx")))),
        candidate_row("task", Some((Some("q"), None))),
        candidate_row("task", Some((None, None))),
        candidate_row("task", Some((Some(""), Some("")))),
        candidate_row("task", Some((Some("null"), Some("null")))),
    ];

    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "q", "ctx", records.clone())
        ),
        Some(json!({ "indices": [] }))
    );
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "", "", records.clone())
        ),
        Some(json!({ "indices": [4] }))
    );
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "null", "null", records)
        ),
        Some(json!({ "indices": [5] }))
    );
}

#[test]
fn candidates_preserve_duplicate_rows_in_input_order_and_handle_empty_input() {
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "q", "c", vec![])
        ),
        Some(json!({ "indices": [] }))
    );

    let hit = candidate_row("task", Some((Some("q"), Some("c"))));
    let miss = candidate_row("task", None);
    let records = vec![
        hit.clone(),
        hit.clone(),
        miss.clone(),
        hit.clone(),
        hit.clone(),
        miss,
        hit.clone(),
        hit,
    ];
    assert_eq!(
        MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "q", "c", records)
        ),
        Some(json!({ "indices": [0, 1, 3, 4, 6, 7] }))
    );
}

#[test]
fn wrong_operation_unicode_schema_and_types_decline_before_filtering() {
    let valid_binding = binding_request("q", "c");
    let valid_row = candidate_row("task", Some((Some("q"), Some("c"))));
    let valid_candidates = candidates_request("task", "q", "c", vec![valid_row.clone()]);

    for bad_op in [
        "",
        "recall",
        "analysis",
        "analysis_binding",
        "analysis_candidates",
    ] {
        assert!(MemoryAnalysis::evaluate(bad_op, &valid_binding).is_none());
        assert!(MemoryAnalysis::evaluate(bad_op, &valid_candidates).is_none());
    }

    for non_obj in [json!(null), json!(false), json!(0), json!("x"), json!([])] {
        assert!(MemoryAnalysis::evaluate("analysis-binding", &non_obj).is_none());
        assert!(MemoryAnalysis::evaluate("analysis-candidates", &non_obj).is_none());
    }

    for bad_unicode in [json!("0.0.0"), json!(""), json!(null), json!(17)] {
        let mut b = valid_binding.clone();
        b["unicode"] = bad_unicode.clone();
        assert!(MemoryAnalysis::evaluate("analysis-binding", &b).is_none());

        let mut c = valid_candidates.clone();
        c["unicode"] = bad_unicode;
        assert!(MemoryAnalysis::evaluate("analysis-candidates", &c).is_none());
    }

    for bad_binding_payload in [
        json!({ "unicode": MemoryTerms::version(), "question": "q" }),
        json!({ "unicode": MemoryTerms::version(), "question": "q", "context": "c", "extra": 1 }),
        json!({ "unicode": MemoryTerms::version(), "question": "q", "other": "c" }),
        json!({ "unicode": MemoryTerms::version(), "question": null, "context": "" }),
        json!({ "unicode": MemoryTerms::version(), "question": "", "context": false }),
        json!({ "unicode": MemoryTerms::version(), "question": "\n", "context": 0 }),
        json!({ "unicode": MemoryTerms::version(), "question": [], "context": "c" }),
        json!({ "unicode": MemoryTerms::version(), "question": "q", "context": {} }),
    ] {
        assert!(MemoryAnalysis::evaluate("analysis-binding", &bad_binding_payload).is_none());
    }

    for bad_candidates_payload in [
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q", "context": "c" },
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q", "context": "c" },
            "records": [],
            "extra": true,
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": null,
            "binding": { "question": "q", "context": "c" },
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": null,
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q" },
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q", "context": "c", "inputs": "00" },
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": null, "context": "c" },
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q", "context": 1 },
            "records": [],
        }),
        json!({
            "unicode": MemoryTerms::version(),
            "scope": "task",
            "binding": { "question": "q", "context": "c" },
            "records": null,
        }),
    ] {
        assert!(MemoryAnalysis::evaluate("analysis-candidates", &bad_candidates_payload).is_none());
    }

    // Malformed rows must decline even when an earlier row matched or row.scope != scope.
    for bad_row in [
        json!(null),
        json!([]),
        json!({ "scope": "other" }),
        json!({ "scope": "other", "analysis": null, "id": "extra" }),
        json!({ "scope": "other", "other": null }),
        json!({ "scope": 1, "analysis": null }),
        json!({ "scope": "other", "analysis": false }),
        json!({ "scope": "other", "analysis": [] }),
        json!({ "scope": "other", "analysis": "text" }),
        json!({ "scope": "other", "analysis": { "question": "q" } }),
        json!({
            "scope": "other",
            "analysis": { "question": "q", "context": "c", "inputs": "00" }
        }),
        json!({ "scope": "other", "analysis": { "question": "q", "other": "c" } }),
        json!({ "scope": "other", "analysis": { "question": 1, "context": "c" } }),
        json!({ "scope": "task", "analysis": { "question": "miss", "context": false } }),
        json!({ "scope": "other", "analysis": { "question": "q", "context": [] } }),
    ] {
        assert!(MemoryAnalysis::evaluate(
            "analysis-candidates",
            &candidates_request("task", "q", "c", vec![valid_row.clone(), bad_row])
        )
        .is_none());
    }
}
