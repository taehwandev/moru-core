use super::*;
use serde_json::json;
fn row() -> Json {
    json!({"user_prompts":0,"hook_denials":0,"moru_hook_denials":0,
    "moru_injected_chars":0,"moru_injected_events":0,"policy_notes":0,"stop_hook_blocks":0,
    "tool_calls":0,"tools":{},"guidance_reads":0,"lifecycle_calls":{},"lifecycle_total":0,"guidance_bash_reads":0})
}
fn shared() -> Json {
    json!({"notes":{},"denials":{},"hook_latency":{}})
}

#[test]
fn attachment_context_and_plain_stdout_keep_counts_without_raw_commands() {
    let mut row = row();
    let mut shared = shared();
    let value = Py::parse(r#"{"type":"hook_additional_context","content":["Moru policy note: /Users/private/file 0123456789abcdef toolu_foo","Tao Agent OS continuation guidance"]}"#).unwrap();
    OverheadHooks::attachment(&value, &mut row, &mut shared).unwrap();
    assert_eq!(row["policy_notes"], 1);
    assert_eq!(row["moru_injected_events"], 1);
    assert_eq!(shared["notes"]["Moru policy note: <path> <id> <toolu>"], 1);
    let value = Py::parse(r#"{"type":"hook_blocking_error","command":"/private/path/moru-hook workflow query --private", "hookEvent":"Stop","durationMs":"١_٢.٥","stdout":"hello","blockingError":"denied"}"#).unwrap();
    let before = row["moru_injected_chars"].as_i64().unwrap();
    OverheadHooks::attachment(&value, &mut row, &mut shared).unwrap();
    assert_eq!(row["moru_injected_chars"], before + 11);
    assert_eq!(shared["hook_latency"]["Stop:workflow query"], json!([12.5]));
    assert!(!shared.to_string().contains("--private"));
}
#[test]
fn denial_redacts_prefix_and_moru_injection_but_normal_prompt_only_counts() {
    let mut row = row();
    let mut shared = shared();
    let value = Py::parse(r#"{"message":{"content":[{"type":"tool_result","is_error":true,"content":"PreToolUse:Bash hook error: Moru worktree gate /tmp/secret"}]}}"#).unwrap();
    OverheadHooks::user(&value, &mut row, &mut shared).unwrap();
    assert_eq!(row["hook_denials"], 1);
    assert_eq!(row["moru_hook_denials"], 1);
    assert_eq!(shared["denials"]["Moru worktree gate <path>"], 1);
    OverheadHooks::user(
        &Py::parse(r#"{"message":{"content":"private prompt"}}"#).unwrap(),
        &mut row,
        &mut shared,
    )
    .unwrap();
    assert_eq!(row["user_prompts"], 1);
    assert!(!shared.to_string().contains("private prompt"));
}
#[test]
fn tools_exclude_search_and_stop_counters_and_nonfinite_decline() {
    let mut row = row();
    let mut shared = shared();
    for command in [
        "rg 'moru-hook start'",
        "moru-hook workflow query",
        "cat /repo/moru-core/docs/a.md",
    ] {
        let input = Value::from(json!({"command":command}));
        OverheadHooks::tool("Bash", &input, &[], &mut row).unwrap();
    }
    assert_eq!(row["tool_calls"], 3);
    assert_eq!(row["lifecycle_total"], 1);
    assert_eq!(row["guidance_bash_reads"], 1);
    OverheadHooks::stop(&Py::parse(r#"{"hookInfos":[{"command":"moru-hook finish","durationMs":"bad"}],"preventedContinuation":true}"#).unwrap(), &mut row, &mut shared).unwrap();
    assert_eq!(row["stop_hook_blocks"], 1);
    assert_eq!(shared["hook_latency"]["Stop:finish"], json!([]));
    assert!(OverheadHooks::stop(
        &Py::parse(r#"{"hookInfos":[{"command":"moru-hook finish","durationMs":NaN}]}"#).unwrap(),
        &mut row,
        &mut shared
    )
    .is_none());
    row["tool_calls"] = i64::MAX.into();
    assert!(OverheadHooks::tool("Other", &Value::Null, &[], &mut row).is_none());
}

#[test]
fn invalid_and_missing_duration_materialize_keys_without_losing_prior_samples() {
    let mut row = row();
    let mut shared = shared();
    for (key, value) in [
        ("missing", Value::Null),
        ("invalid", Value::String("bad".into())),
        ("list", Value::Array(Vec::new())),
    ] {
        latency(&mut shared, key, &value).unwrap();
        assert_eq!(shared["hook_latency"][key], json!([]));
    }
    latency(&mut shared, "existing", &Py::parse("12.5").unwrap()).unwrap();
    latency(&mut shared, "existing", &Value::Null).unwrap();
    assert_eq!(shared["hook_latency"]["existing"], json!([12.5]));
    OverheadHooks::attachment(
        &Py::parse(r#"{"type":"hook_success","command":"moru-hook status"}"#).unwrap(),
        &mut row,
        &mut shared,
    )
    .unwrap();
    assert_eq!(shared["hook_latency"]["?:status"], json!([]));
}
