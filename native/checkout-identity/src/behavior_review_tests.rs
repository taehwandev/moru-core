use super::*;

fn record() -> Value {
    PythonJson::parse(r#"{"phase":"finished","runtime_path":true,"runtime_digest":NaN,"status":"ok","events":[{"event_type":"review.record_initialized"},{"event_type":"review.finished","status":"ok"}],"response":"private"}"#).unwrap()
}

#[test]
fn normalizes_only_content_free_events_and_preserves_python_spacing() {
    let result = BehaviorReview::normalize(&record(), "agy", "case-1")
        .unwrap_or_else(|_| panic!("valid record rejected"));
    assert_eq!(python_spacing(&result), br#"{"schema_version": 1, "runs": [{"provider": "agy", "case_id": "case-1", "events": [{"kind": "durable_record_written"}, {"kind": "final", "status": "ok"}]}]}"#);
}

#[test]
fn rejects_receipt_mismatch_invalid_provider_and_invalid_case() {
    for (provider, case) in [("other", "case"), ("agy", ""), ("agy", "한글")] {
        assert!(matches!(
            BehaviorReview::normalize(&record(), provider, case),
            Err(Failure::Invalid)
        ));
    }
    let bad = PythonJson::parse(r#"{"phase":"finished","runtime_path":"x","runtime_digest":"x","status":"blocked","events":[{"event_type":"review.finished","status":"ok"}]}"#).unwrap();
    assert!(matches!(
        BehaviorReview::normalize(&bad, "agy", "case"),
        Err(Failure::Invalid)
    ));
}

#[test]
fn rejects_content_fields_before_projection() {
    let bad = PythonJson::parse(r#"{"phase":"finished","runtime_path":"x","runtime_digest":"x","status":"ok","events":[{"event_type":"review.finished","status":"ok","content":"private"}]}"#).unwrap();
    assert!(matches!(
        BehaviorReview::normalize(&bad, "agy", "case"),
        Err(Failure::Invalid)
    ));
}
