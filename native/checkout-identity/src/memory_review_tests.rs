use super::*;

fn packet(records: Value) -> Value {
    json!({"unicode":MemoryTerms::version(),"today":"2026-11-13","horizon":"2026-11-27","records":records})
}

fn fused(records: Value) -> Value {
    let mut value = packet(records);
    value["statuses"] = json!(["active", "pending", "approved"]);
    value
}

#[test]
fn partition_preserves_inclusive_expiry_and_exclusive_upcoming_start() {
    let value = packet(json!([
        {"id":"a","review":"2026-11-12"},{"id":"b","review":"2026-11-13"},
        {"id":"c","review":"2026-11-14"},{"id":"d","review":"2026-11-27"},
        {"id":"e","review":"2026-11-28"}
    ]));
    assert_eq!(
        MemoryReview::evaluate("review-partition", &value),
        Some(json!({"live":[0,1,2,3,4],"expired":[0,1],"expiring":[2,3]}))
    );
}

#[test]
fn partition_uses_last_date_for_every_duplicate_id_without_reordering() {
    let value = packet(json!([
        {"id":"z","review":"2026-11-13"},{"id":"a","review":"2026-11-12"},
        {"id":"b","review":"2026-11-27"},{"id":"a","review":"2026-12-01"}
    ]));
    assert_eq!(
        MemoryReview::evaluate("review-partition", &value),
        Some(json!({"live":[0,1,2,3],"expired":[0],"expiring":[2]}))
    );
}

#[test]
fn fused_inputs_sort_live_statuses_stably_and_ignore_retired_dates() {
    let value = fused(json!([
        {"id":"b","status":"pending","review":"2026-11-13"},
        {"id":"a","status":"active","review":"2026-11-12"},
        {"id":"x","status":"retired","review":null},
        {"id":"a","status":"approved","review":"2026-12-01"},
        {"id":"c","status":"active","review":"2026-11-27"},
        {"id":"0","status":"ACTIVE","review":"invalid"}
    ]));
    assert_eq!(
        MemoryReview::evaluate("review-findings", &value),
        Some(json!({"live":[1,3,0,4],"expired":[0],"expiring":[4]}))
    );
}

#[test]
fn strict_date_parser_preserves_leap_centuries_and_calendar_extremes() {
    for valid in ["0001-01-01", "2000-02-29", "2024-02-29", "9999-12-31"] {
        assert!(MemoryReview::evaluate(
            "review-partition",
            &packet(json!([{"id":"a","review":valid}]))
        )
        .is_some());
    }
    for invalid in [
        "0000-01-01",
        "1900-02-29",
        "2100-02-29",
        "2026-02-29",
        "2026-04-31",
        "20261113",
        "2026-W46-5",
        "٢٠٢٦-11-13",
        "2026-1-13",
        "",
    ] {
        assert!(MemoryReview::evaluate(
            "review-partition",
            &packet(json!([{"id":"a","review":invalid}]))
        )
        .is_none());
    }
}

#[test]
fn zero_or_reverse_horizon_never_creates_overlapping_buckets() {
    let mut value = packet(json!([
        {"id":"a","review":"2026-11-12"},{"id":"b","review":"2026-11-13"},
        {"id":"c","review":"2026-11-14"}
    ]));
    for horizon in ["2026-11-13", "2026-11-01"] {
        value["horizon"] = json!(horizon);
        assert_eq!(
            MemoryReview::evaluate("review-partition", &value),
            Some(json!({"live":[0,1,2],"expired":[0,1],"expiring":[]}))
        );
    }
}

#[test]
fn empty_payloads_keep_complete_empty_arrays() {
    for (operation, value) in [
        ("review-partition", packet(json!([]))),
        ("review-findings", fused(json!([]))),
    ] {
        assert_eq!(
            MemoryReview::evaluate(operation, &value),
            Some(json!({"live":[],"expired":[],"expiring":[]}))
        );
    }
}

#[test]
fn closed_schema_rejects_unknown_operations_versions_and_payload_fields() {
    let valid = packet(json!([]));
    assert!(MemoryReview::evaluate("review", &valid).is_none());
    for key in ["unicode", "today", "horizon", "records"] {
        let mut value = valid.clone();
        value.as_object_mut().unwrap().remove(key);
        assert!(MemoryReview::evaluate("review-partition", &value).is_none());
    }
    for (key, bad) in [
        ("unicode", json!("wrong")),
        ("today", json!("invalid")),
        ("horizon", json!(true)),
        ("records", json!({})),
        ("extra", json!(1)),
    ] {
        let mut value = valid.clone();
        value[key] = bad;
        assert!(MemoryReview::evaluate("review-partition", &value).is_none());
    }
    let mut bad = fused(json!([]));
    bad["statuses"] = json!([1]);
    assert!(MemoryReview::evaluate("review-findings", &bad).is_none());
}

#[test]
fn invalid_later_rows_never_return_a_valid_prefix() {
    for bad in [
        json!({"id":"b"}),
        json!({"id":1,"review":"2026-11-13"}),
        json!({"id":"b","review":null}),
        json!({"id":"b","review":"bad"}),
        json!({"id":"b","review":"2026-11-13","extra":1}),
    ] {
        assert!(MemoryReview::evaluate(
            "review-partition",
            &packet(json!([
                {"id":"a","review":"2026-11-13"},bad
            ]))
        )
        .is_none());
    }
    for bad in [
        json!({"id":"b","status":"retired","review":1}),
        json!({"id":"b","status":[],"review":null}),
        json!({"id":"b","status":"active","review":null}),
    ] {
        assert!(MemoryReview::evaluate("review-findings", &fused(json!([bad]))).is_none());
    }
}
