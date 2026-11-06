use super::*;
#[test]
fn assistant_ids_use_python_numeric_equality_and_usage_counts_once() {
    let text = concat!(
        "not-json\n[]\n",
        "{\"type\":\"assistant\",\"message\":{\"id\":1,\"usage\":{\"input_tokens\":\"١_٢\",\"output_tokens\":2.9}}}\n",
        "{\"type\":\"assistant\",\"message\":{\"id\":true,\"usage\":{\"input_tokens\":99}}}\n",
        "{\"type\":\"assistant\",\"message\":{\"id\":1.0}}\n",
        "{\"type\":\"assistant\",\"message\":{\"id\":NaN}}\n",
        "{\"type\":\"assistant\",\"message\":{\"id\":NaN}}\n"
    );
    let value =
        OverheadSession::measure("session.jsonl", text, &[], &[Json::Null, Json::Null]).unwrap();
    assert_eq!(value["row"]["assistant_turns"], 2);
    assert_eq!(value["row"]["tok_input"], 12);
    assert_eq!(value["row"]["tok_output"], 2);
    assert_eq!(value["row"]["tok_total"], 14);
    assert_eq!(value["row"]["project_dir"], "");
    assert_eq!(
        value["row"].as_object().unwrap().keys().next().unwrap(),
        "assistant_turns"
    );
    assert_eq!(
        value["shared"],
        json!({"notes":{},"denials":{},"hook_latency":{}})
    );
}
#[test]
fn windows_keep_first_cwd_and_compare_offsets_preserving_original_zone() {
    let text = concat!(
        "{\"cwd\":\"/core/project\",\"timestamp\":\"2026-11-06T09:00:00+09:00\",\"type\":\"assistant\",\"uuid\":\"old\"}\n",
        "{\"cwd\":\"/other\",\"timestamp\":\"2026-11-06T09:00:01.123+09:00\",\"type\":\"assistant\",\"uuid\":\"in\"}\n"
    );
    let value = OverheadSession::measure(
        "/tmp/project/session.jsonl",
        text,
        &["/core".into()],
        &[json!("2026-11-06T00:00:01+00:00"), Json::Null],
    )
    .unwrap();
    assert_eq!(value["row"]["assistant_turns"], 1);
    assert_eq!(value["row"]["cwd"], "/core/project");
    assert_eq!(value["row"]["moru_core"], true);
    assert_eq!(value["row"]["first_ts"], "2026-11-06T09:00:01.123000+09:00");
    assert_eq!(value["row"]["project_dir"], "project");
}
#[test]
fn timestamp_invalid_and_unknown_grammar_are_distinct() {
    assert!(matches!(
        OverheadStamp::parse("2026-11-06T+00:00"),
        Some(None)
    ));
    assert!(matches!(OverheadStamp::parse("bad"), Some(None)));
    assert!(matches!(
        OverheadStamp::parse("2026-02-29T01:00:00"),
        Some(None)
    ));
    assert!(OverheadStamp::parse("2026-11-06T01:02:03.1").is_none());
    let date = OverheadStamp::parse("2024-02-29").unwrap().unwrap();
    assert_eq!(date.iso, "2024-02-29T00:00:00");
    let aware = OverheadStamp::parse("2024-02-29T00:00:00Z")
        .unwrap()
        .unwrap();
    assert!(date.compare(&aware).is_none());
    assert!(SessionNumber::integer(&Value::String("\x1c1".into())).is_none());
}
#[test]
fn unsupported_partial_mutation_declines_the_entire_session() {
    let text = "{\"type\":\"assistant\",\"message\":{\"id\":[1]}}\n";
    assert!(OverheadSession::measure("x", text, &[], &[Json::Null, Json::Null]).is_none());
    let text = "{\"type\":\"assistant\",\"message\":{\"usage\":{\"input_tokens\":\"bad\"}}}\n";
    assert!(OverheadSession::measure("x", text, &[], &[Json::Null, Json::Null]).is_none());
}

#[test]
fn integer_string_limit_counts_leading_unicode_zeroes_not_signs_or_underscores() {
    assert_eq!(SessionNumber::string_with_limit(" +٠_٠_١ ", 3), Some(1));
    assert_eq!(SessionNumber::string_with_limit("-0001", 3), None);
    assert_eq!(SessionNumber::string_with_limit("０_０_０_１", 3), None);
    assert_eq!(
        SessionNumber::string_with_limit(&format!("{}1", "0".repeat(4300)), 4300),
        None
    );
    assert_eq!(
        SessionNumber::string_with_limit(&format!("{}1", "0".repeat(4300)), 0),
        Some(1)
    );
}
