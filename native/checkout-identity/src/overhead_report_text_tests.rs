use super::OverheadReportText;
use serde_json::{json, Value};

fn report() -> Value {
    json!({"generated_at":"now", "window":{"since":"then","until":"now"},
        "all":{"sessions":0}, "moru_core":{"sessions":0}, "other_projects":{"sessions":0},
        "moru_hook_latency_ms_from_transcripts":{},"top_policy_notes":[],"top_hook_denials":[]})
}

#[test]
fn json_indentation_order_unicode_and_empty_containers_match_python() {
    let value: Value =
        serde_json::from_str(r#"{"z":"한😀\u0000\n\"\\","a":[true,null,{},[]]}"#).unwrap();
    assert_eq!(
        OverheadReportText::json(&value).unwrap(),
        concat!(
            "{\n  \"z\": \"한😀\\u0000\\n\\\"\\\\\",\n  \"a\": [\n",
            "    true,\n    null,\n    {},\n    []\n  ]\n}"
        )
    );
}

#[test]
fn json_keeps_python_float_notation_and_integer_distinction() {
    let value: Value =
        serde_json::from_str("[1,1.0,-0.0,1e-5,1e16,1e15,18446744073709551615]").unwrap();
    assert_eq!(OverheadReportText::json(&value).unwrap(), concat!(
        "[\n  1,\n  1.0,\n  -0.0,\n  1e-05,\n  1e+16,\n  1000000000000000.0,\n  18446744073709551615\n]"));
}

#[test]
fn markdown_empty_groups_preserve_none_zero_and_final_blank_lines() {
    let actual = OverheadReportText::markdown(&report()).unwrap();
    let mut expected = concat!(
        "# Moru workflow overhead\n\nGenerated: now  \nWindow: then .. now\n\n",
        "Sessions: all=0, moru-core=0, other=0\n\n"
    )
    .to_owned();
    for group in ["all", "moru_core", "other_projects"] {
        expected += &format!("## {group} (median / p90 per session)\n\n");
        expected += concat!("| metric | median | p90 | n |\n|---|---|---|---|\n",
            "| assistant turns | None | None | 0 |\n| tool calls | None | None | 0 |\n",
            "| lifecycle (launcher) Bash calls | None | None | 0 |\n| policy notes | None | None | 0 |\n",
            "| hook denials (all) | None | None | 0 |\n| Moru hook denials | None | None | 0 |\n",
            "| guidance doc Reads | None | None | 0 |\n| guidance doc Bash reads | None | None | 0 |\n",
            "| total tokens | None | None | 0 |\n| output tokens | None | None | 0 |\n",
            "| Moru-injected tokens (chars/4) | None | None | 0 |\n\n",
            "- lifecycle share of tool calls: None%\n- injected tokens vs new input: None%\n",
            "- lifecycle subcommands: null\n\n");
    }
    expected += concat!(
        "## Moru hook latency from transcripts (ms)\n\n| hook | n | median | p90 |\n",
        "|---|---|---|---|\n\n## Top policy notes\n\n\n## Top hook denials\n\n"
    );
    assert_eq!(actual, expected);
}

#[test]
fn markdown_compact_lifecycle_uses_ascii_escapes_and_python_separators() {
    let mut value = report();
    value["all"]["lifecycle_calls_by_subcommand_total"] =
        serde_json::from_str(r#"{"한😀\u007f":1,"second":2}"#).unwrap();
    value["all"]["assistant_turns"] = json!({"n":2,"median":-0.0,"p90":1.0});
    value["moru_hook_latency_ms_from_transcripts"] =
        json!({"Stop:finish":{"n":1,"median":2.5,"p90":2.5}});
    value["top_policy_notes"] = json!([{"count":2,"message":"정책\ncontinued"}]);
    let text = OverheadReportText::markdown(&value).unwrap();
    assert!(text.contains("| assistant turns | -0.0 | 1.0 | 2 |\n"));
    assert!(text.contains(
        "- lifecycle subcommands: {\"\\ud55c\\ud83d\\ude00\\u007f\": 1, \"second\": 2}\n"
    ));
    assert!(text.contains("| Stop:finish | 1 | 2.5 | 2.5 |\n"));
    assert!(
        text.contains("## Top policy notes\n\n1. (2) 정책\ncontinued\n\n## Top hook denials\n\n")
    );
}

#[test]
fn malformed_markdown_shapes_and_excessive_json_depth_decline() {
    assert!(OverheadReportText::markdown(&Value::Null).is_none());
    let mut value = report();
    value["all"]["assistant_turns"] = json!([1]);
    assert!(OverheadReportText::markdown(&value).is_none());
    value = report();
    value["top_policy_notes"] = json!([{"message":"missing count"}]);
    assert!(OverheadReportText::markdown(&value).is_none());
    let mut nested = Value::Null;
    for _ in 0..129 {
        nested = Value::Array(vec![nested]);
    }
    assert!(OverheadReportText::json(&nested).is_none());
}
