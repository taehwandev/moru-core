use super::OverheadReportText;
use crate::python_json::PythonJson;
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

#[test]
fn lossless_json_preserves_large_integers_nonfinite_values_and_duplicate_order() {
    let value = PythonJson::parse(concat!(
        "[184467440737095516160123456789,-184467440737095516160123456789,",
        "NaN,Infinity,-Infinity,-0.0,{\"b\":1,\"a\":0,\"b\":NaN}]"
    ))
    .unwrap();
    assert_eq!(
        OverheadReportText::json_value(&value).unwrap(),
        concat!(
        "[\n  184467440737095516160123456789,\n  -184467440737095516160123456789,\n",
        "  NaN,\n  Infinity,\n  -Infinity,\n  -0.0,\n  {\n    \"b\": NaN,\n    \"a\": 0\n  }\n]"
    )
    );
}

#[test]
fn lossless_markdown_uses_python_display_and_json_lifecycle_spelling() {
    let value = PythonJson::parse(r#"{
        "generated_at":true,"window":{"since":["한",null],"until":{"x":false}},
        "all":{"sessions":184467440737095516160123456789,
            "assistant_turns":{"n":true,"median":NaN,"p90":-Infinity},
            "tool_calls":{"n":null,"median":[null,true,{"한":Infinity}],"p90":{"x":false}},
            "lifecycle_share_of_tool_calls_pct":Infinity,"injected_tokens_vs_new_input_pct":-0.0,
            "lifecycle_calls_by_subcommand_total":{"한😀":184467440737095516160123456789,"other":[NaN,true,null]}},
        "moru_core":{"sessions":null},"other_projects":{"sessions":[1,2]},
        "moru_hook_latency_ms_from_transcripts":{"Stop":{"n":184467440737095516160123456789,"median":Infinity,"p90":NaN}},
        "top_policy_notes":[{"count":true,"message":[null,{"한":NaN}]}],
        "top_hook_denials":[{"count":184467440737095516160123456789,"message":null}]}
    "#).unwrap();
    let text = OverheadReportText::markdown_value(&value).unwrap();
    assert!(text.starts_with(concat!(
        "# Moru workflow overhead\n\nGenerated: True  \n",
        "Window: ['한', None] .. {'x': False}\n\n",
        "Sessions: all=184467440737095516160123456789, moru-core=None, other=[1, 2]\n\n"
    )));
    assert!(text.contains("| assistant turns | nan | -inf | True |\n"));
    assert!(text.contains("| tool calls | [None, True, {'한': inf}] | {'x': False} | None |\n"));
    assert!(text.contains(
        "- lifecycle share of tool calls: inf%\n- injected tokens vs new input: -0.0%\n"
    ));
    assert!(text.contains(concat!(
        "- lifecycle subcommands: {\"\\ud55c\\ud83d\\ude00\": ",
        "184467440737095516160123456789, \"other\": [NaN, true, null]}\n"
    )));
    assert!(text.contains("| Stop | 184467440737095516160123456789 | inf | nan |\n"));
    assert!(text.ends_with(concat!(
        "## Top policy notes\n\n1. (True) [None, {'한': nan}]\n\n",
        "## Top hook denials\n\n1. (184467440737095516160123456789) None\n"
    )));
}

#[test]
fn lossless_markdown_requires_structural_objects_and_keys() {
    for raw in [
        "{}",
        "null",
        r#"{"window":[]}"#,
        r#"{"window":{"since":"then","until":"now"}}"#,
    ] {
        let value = PythonJson::parse(raw).unwrap();
        assert!(OverheadReportText::markdown_value(&value).is_none());
    }
    assert!(PythonJson::parse(r#""\ud800""#).is_none());
}
