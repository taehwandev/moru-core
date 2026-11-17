use super::BehaviorTrace;
use serde_json::{json, Value};

fn make_input(provider: &str, case_id: &str, events: Value) -> Value {
    json!({
        "schema_version": 1,
        "provider": provider,
        "case_id": case_id,
        "events": events,
    })
}

#[test]
fn normalizes_all_supported_events_and_statuses() {
    let input = make_input(
        "agy",
        "Case_01-alpha",
        json!([
            { "event_type": "review.record_initialized" },
            { "event_type": "review.startup_retry" },
            { "event_type": "review.prompt_submitted" },
            { "event_type": "review.session_observed" },
            { "event_type": "review.submission_ambiguous" },
            { "event_type": "task.claimed" },
            { "event_type": "review.cancel_requested" },
            { "event_type": "task.cancelled" },
            { "event_type": "review.cancel_confirmed" },
            { "event_type": "worker.cancelled" },
            { "event_type": "review.empty_result" },
            { "event_type": "worker.failure" },
            { "event_type": "worker.result" },
            { "event_type": "review.finished", "status": "ok" }
        ]),
    );

    let out = BehaviorTrace::normalize(&input).expect("valid trace should normalize");
    assert_eq!(
        out,
        json!({
            "schema_version": 1,
            "runs": [{
                "provider": "agy",
                "case_id": "Case_01-alpha",
                "events": [
                    { "kind": "durable_record_written" },
                    { "kind": "startup_retry_before_submit" },
                    { "kind": "prompt_submitted" },
                    { "kind": "session_observed" },
                    { "kind": "submission_ambiguous" },
                    { "kind": "worker_started" },
                    { "kind": "cancel_requested" },
                    { "kind": "cancel_requested" },
                    { "kind": "cancel_confirmed" },
                    { "kind": "cancel_confirmed" },
                    { "kind": "empty_result_detected" },
                    { "kind": "worker_failed" },
                    { "kind": "run_completed" },
                    { "kind": "final", "status": "ok" }
                ]
            }]
        })
    );

    for (provider, status) in [("codex", "blocked"), ("claude", "needs_inspection")] {
        let alt = make_input(
            provider,
            "case_2",
            json!([{ "event_type": "review.finished", "status": status }]),
        );
        let normalized = BehaviorTrace::normalize(&alt).expect("provider/status should succeed");
        assert_eq!(normalized["runs"][0]["provider"], provider);
        assert_eq!(normalized["runs"][0]["events"][0]["status"], status);
    }
}

#[test]
fn preserves_repeated_prompt_events_and_exact_order() {
    let input = make_input(
        "codex",
        "repeat-prompts",
        json!([
            { "event_type": "review.prompt_submitted" },
            { "event_type": "review.prompt_submitted" },
            { "event_type": "review.startup_retry" },
            { "event_type": "review.prompt_submitted" },
            { "event_type": "review.finished", "status": "ok" }
        ]),
    );

    let out = BehaviorTrace::normalize(&input).expect("repeated prompts must normalize");
    assert_eq!(
        out["runs"][0]["events"],
        json!([
            { "kind": "prompt_submitted" },
            { "kind": "prompt_submitted" },
            { "kind": "startup_retry_before_submit" },
            { "kind": "prompt_submitted" },
            { "kind": "final", "status": "ok" }
        ])
    );
}

#[test]
fn rejects_missing_early_and_duplicate_finals() {
    let no_final = make_input(
        "agy",
        "no-final",
        json!([
            { "event_type": "task.claimed" },
            { "event_type": "worker.result" }
        ]),
    );
    assert!(BehaviorTrace::normalize(&no_final).is_err());

    let early_final = make_input(
        "agy",
        "early-final",
        json!([
            { "event_type": "review.finished", "status": "ok" },
            { "event_type": "worker.result" }
        ]),
    );
    assert!(BehaviorTrace::normalize(&early_final).is_err());

    let duplicate_final = make_input(
        "agy",
        "dup-final",
        json!([
            { "event_type": "review.finished", "status": "ok" },
            { "event_type": "review.finished", "status": "blocked" }
        ]),
    );
    assert!(BehaviorTrace::normalize(&duplicate_final).is_err());
}

#[test]
fn rejects_unknown_events_and_invalid_status_usage() {
    let unknown = make_input(
        "claude",
        "unknown-ev",
        json!([
            { "event_type": "agent.raw_thought" },
            { "event_type": "review.finished", "status": "ok" }
        ]),
    );
    assert_eq!(BehaviorTrace::normalize(&unknown), Err("unknown_event"));

    let nonfinal_status = make_input(
        "claude",
        "bad-status",
        json!([
            { "event_type": "worker.result", "status": "ok" },
            { "event_type": "review.finished", "status": "ok" }
        ]),
    );
    assert_eq!(
        BehaviorTrace::normalize(&nonfinal_status),
        Err("invalid_event")
    );

    for bad_final in [
        json!({ "event_type": "review.finished" }),
        json!({ "event_type": "review.finished", "status": "done" }),
        json!({ "event_type": "review.finished", "status": 1 }),
    ] {
        let input = make_input("claude", "bad-final", json!([bad_final]));
        assert!(BehaviorTrace::normalize(&input).is_err());
    }
}

#[test]
fn rejects_content_leakage_fields_at_root_and_event_levels() {
    let root_leak = json!({
        "schema_version": 1,
        "provider": "agy",
        "case_id": "leak-root",
        "prompt": "secret user prompt",
        "events": [{ "event_type": "review.finished", "status": "ok" }]
    });
    assert!(BehaviorTrace::normalize(&root_leak).is_err());

    for leaked_field in ["prompt", "transcript", "command", "content", "raw"] {
        let mut ev = serde_json::Map::new();
        ev.insert("event_type".to_string(), json!("review.prompt_submitted"));
        ev.insert(leaked_field.to_string(), json!("sensitive payload"));
        let input = make_input(
            "agy",
            "leak-event",
            json!([
                Value::Object(ev),
                { "event_type": "review.finished", "status": "ok" }
            ]),
        );
        assert_eq!(BehaviorTrace::normalize(&input), Err("invalid_event"));
    }
}

#[test]
fn rejects_malformed_types_versions_providers_and_event_bounds() {
    assert!(BehaviorTrace::normalize(&json!(["not-an-object"])).is_err());
    assert!(BehaviorTrace::normalize(&json!({ "schema_version": 1 })).is_err());

    for bad_ver in [json!(0), json!(2), json!("1"), json!(1.0), json!(null)] {
        let input = json!({
            "schema_version": bad_ver,
            "provider": "codex",
            "case_id": "ver-check",
            "events": [{ "event_type": "review.finished", "status": "ok" }]
        });
        assert!(BehaviorTrace::normalize(&input).is_err());
    }

    for bad_provider in [json!("openai"), json!(""), json!("AGY"), json!(42)] {
        let input = json!({
            "schema_version": 1,
            "provider": bad_provider,
            "case_id": "prov-check",
            "events": [{ "event_type": "review.finished", "status": "ok" }]
        });
        assert!(BehaviorTrace::normalize(&input).is_err());
    }

    assert!(BehaviorTrace::normalize(&make_input("agy", "empty-ev", json!([]))).is_err());
    assert!(BehaviorTrace::normalize(&make_input("agy", "non-arr", json!({}))).is_err());
    assert!(BehaviorTrace::normalize(&make_input("agy", "bad-item", json!([123]))).is_err());

    let mut max_ok: Vec<Value> = (0..2047)
        .map(|_| json!({ "event_type": "review.prompt_submitted" }))
        .collect();
    max_ok.push(json!({ "event_type": "review.finished", "status": "ok" }));
    assert!(BehaviorTrace::normalize(&make_input("agy", "max-2048", Value::Array(max_ok))).is_ok());

    let mut too_many: Vec<Value> = (0..2048)
        .map(|_| json!({ "event_type": "review.prompt_submitted" }))
        .collect();
    too_many.push(json!({ "event_type": "review.finished", "status": "ok" }));
    assert!(
        BehaviorTrace::normalize(&make_input("agy", "over-2048", Value::Array(too_many))).is_err()
    );
}

#[test]
fn validates_case_id_charset_and_length_bounds() {
    let max_id = "a".repeat(80);
    let ok_input = make_input(
        "codex",
        &max_id,
        json!([{ "event_type": "review.finished", "status": "ok" }]),
    );
    assert!(BehaviorTrace::normalize(&ok_input).is_ok());

    let over_max = "a".repeat(81);
    let nul_id = String::from_utf8(vec![b'a', 0, b'b']).expect("valid utf8 with nul");
    for unsafe_id in [
        "",
        over_max.as_str(),
        "../traversal",
        "dir/case",
        "space id",
        "dot.case",
        "colon:case",
        "nonascii-é",
        nul_id.as_str(),
    ] {
        let bad = make_input(
            "codex",
            unsafe_id,
            json!([{ "event_type": "review.finished", "status": "ok" }]),
        );
        assert!(BehaviorTrace::normalize(&bad).is_err());
    }
}
