use super::*;
fn value(text: &str) -> Value {
    PythonJson::parse(text).unwrap()
}

#[test]
fn latest_record_suppresses_active_before_filtering() {
    let data = value(
        r#"{"schema_version":1,"runs":[
        {"evidence_key":"same","state":"running"},
        {"evidence_key":"same","state":"completed"},
        {"evidence_name":"preflight.json","state":"paused"},
        {"evidence_key":"claim","state":"claiming"},
        {"evidence_key":"resume","state":"resuming"}] }"#,
    );
    let bound = NextSession::bindings(&data, "legacy").unwrap();
    assert_eq!(
        bound.keys().map(String::as_str).collect::<Vec<_>>(),
        vec!["legacy", "resume"]
    );
}

#[test]
fn unhashable_latest_state_defers_but_overwritten_state_is_irrelevant() {
    let invalid = value(r#"{"schema_version":1,"runs":[{"evidence_key":"k","state":[]}]}"#);
    assert!(NextSession::bindings(&invalid, "legacy").is_none());
    let repaired = value(
        r#"{"schema_version":1,"runs":[{"evidence_key":"k","state":[]},{"evidence_key":"k","state":"completed"}]}"#,
    );
    assert!(NextSession::bindings(&repaired, "legacy")
        .unwrap()
        .is_empty());
}

#[test]
fn same_session_alias_cli_and_exact_generation() {
    let run = value(r#"{"resume_generation":" 2 "}"#);
    for runtime in ["AGY", " antigravity\t", "cli"] {
        let payload: Value = serde_json::json!({"runtime_session": {"runtime": runtime, "session_id":"ours", "resume_generation":2.0}}).into();
        assert_eq!(
            NextSession::matches(&payload, &run, "antigravity", "ours"),
            Some(true)
        );
        assert_eq!(
            NextSession::matches(&payload, &run, "antigravity", "other"),
            Some(false)
        );
    }
    let payload = value(
        r#"{"runtime_session":{"runtime":"codex","session_id":"ours","resume_generation":9007199254740993}}"#,
    );
    assert_eq!(
        NextSession::matches(
            &payload,
            &value(r#"{"resume_generation":9007199254740992}"#),
            "codex",
            "ours"
        ),
        Some(false)
    );
    assert_eq!(
        NextSession::generation(Some(&value("9007199254740993"))),
        None
    );
}

#[test]
fn missing_and_boolean_generations_follow_python_equality() {
    assert_eq!(
        NextSession::matches(
            &value("{}"),
            &value(r#"{"resume_generation":"bad"}"#),
            "codex",
            "s"
        ),
        None
    );
    let payload = value(r#"{"runtime_session":{"runtime":"codex","session_id":"s"}}"#);
    assert_eq!(
        NextSession::matches(&payload, &value("{}"), "codex", "s"),
        Some(true)
    );
    let payload = value(
        r#"{"runtime_session":{"runtime":"codex","session_id":"s","resume_generation":true}}"#,
    );
    assert_eq!(
        NextSession::matches(
            &payload,
            &value(r#"{"resume_generation":1.9}"#),
            "codex",
            "s"
        ),
        Some(true)
    );
    let payload = value(
        r#"{"runtime_session":{"runtime":"codex","session_id":"s","resume_generation":null}}"#,
    );
    assert_eq!(
        NextSession::matches(&payload, &value("{}"), "codex", "s"),
        Some(false)
    );
}
