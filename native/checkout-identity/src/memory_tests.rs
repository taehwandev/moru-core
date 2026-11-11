use super::*;

fn record(id: &str, body: &str) -> Value {
    json!({"id":id,"body":body,"source":"source","scope":"task",
        "review_on":"2027-01-01","status":"active"})
}
fn query(records: Value, context: &str) -> Value {
    json!({"unicode":MemoryTerms::version(),"scope":"task","today":"2026-11-09",
        "records":records,"context":context})
}

#[test]
fn eligibility_replacements_and_expiry_precede_scoring() {
    let mut retired = record("new","other");
    retired["status"] = json!("retired"); retired["replaces"] = json!("old");
    let mut expired = record("expired","retry_queue"); expired["review_on"] = json!("2026-11-09");
    let payload = query(json!([record("old","retry_queue"),retired,expired,
        record("live","retry_queue")]),"retry_queue");
    assert_eq!(MemoryRecall::evaluate("recall",&payload),Some(json!({"indices":[3]})));
}
#[test]
fn duplicate_id_scores_use_last_value_and_stable_sort() {
    let payload = query(json!([record("same","other"),record("same","retry_queue")]),"retry_queue");
    assert_eq!(MemoryRecall::evaluate("recall",&payload),Some(json!({"indices":[0,1]})));
    let payload = query(json!([record("same","retry_queue"),record("same","other")]),"retry_queue");
    assert_eq!(MemoryRecall::evaluate("recall",&payload),Some(json!({"indices":[]})));
}
#[test]
fn exact_path_weights_and_korean_particle_terms() {
    let payload = query(json!([record("generic","Fix dispatcher worker errors failed slow"),
        record("path","src/dispatch/retry_queue.py")]),
        "Fix dispatcher worker errors failed slow /absolute/src/dispatch/retry_queue.py");
    assert_eq!(MemoryRecall::evaluate("recall",&payload),Some(json!({"indices":[1,0]})));
    let terms = MemoryTerms::terms("프로필에서는 아이랑");
    assert!(terms.0.contains("프로필")); assert!(terms.0.contains("아이"));
    assert!(!MemoryTerms::terms("아이").0.contains("아"));
}
#[test]
fn dates_versions_schema_and_non_authority_queries_decline() {
    for day in ["0000-01-01","2026-02-29","2026-04-31","2026-13-01","20260101"] {
        let mut payload = query(json!([record("a","a")]),""); payload["today"] = json!(day);
        assert!(MemoryRecall::evaluate("recall",&payload).is_none());
    }
    for day in ["2000-02-29","2024-02-29","2026-04-30"] { assert!(MemoryRecord::date(day)); }
    let mut payload = query(json!([]),""); payload["unicode"] = json!("unknown");
    assert!(MemoryRecall::evaluate("recall",&payload).is_none());
    assert!(MemoryRecall::evaluate("capture",&query(json!([]),"")).is_none());
}
