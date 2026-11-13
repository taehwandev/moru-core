use super::*;

fn packet(records: Value) -> Value {
    json!({"unicode":MemoryTerms::version(),"records":records})
}

fn live(records: Value) -> Value {
    let mut value = packet(records);
    value["statuses"] = json!(["active", "pending", "approved"]);
    value
}

fn startup(records: Value, today: i64) -> Value {
    let mut value = packet(records);
    value["today"] = json!(today);
    value
}

fn row(id: &str, scope: &str, body: &str, source: &str, replaces: Value, review: i64) -> Value {
    json!({"id":id,"scope":scope,"body":body,"source":source,"replaces":replaces,"review":review})
}

#[test]
fn live_selection_preserves_status_case_unicode_order_and_duplicate_ties() {
    let value = live(json!([
        {"id":"𐀀","status":"active"},{"id":"a","status":"pending"},
        {"id":"a","status":"approved"},{"id":"0","status":"retired"},
        {"id":"\u{e000}","status":"active"},{"id":"0","status":"ACTIVE"}
    ]));
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-live", &value),
        Some(json!({"indices":[1,2,4,0]}))
    );
    let mut custom = value.clone();
    custom["statuses"] = json!(["retired"]);
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-live", &custom),
        Some(json!({"indices":[3]}))
    );
}

#[test]
fn replacement_findings_keep_input_order_duplicate_targets_and_sorted_duplicates() {
    let value = packet(json!([
        {"id":"b","replaces":"a"},{"id":"a","replaces":null},
        {"id":"c","replaces":"a"},{"id":"a","replaces":"b"},
        {"id":"c","replaces":"a"},{"id":"orphan","replaces":"absent"}
    ]));
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-replacements", &value),
        Some(json!({"findings":[
            {"index":0,"replacements":[3]},{"index":1,"replacements":[0,2,4]},
            {"index":3,"replacements":[0,2,4]}
        ]}))
    );
    let empty = packet(json!([{"id":"","replaces":""},{"id":"a","replaces":null}]));
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-replacements", &empty),
        Some(json!({"findings":[]}))
    );
}

#[test]
fn startup_counts_scope_bridges_and_disjoint_groups_without_fuzzy_comparison() {
    let records = json!([
        row("a", "task", "same", "docs", Value::Null, 10),
        row("b", "task", "same", "docs", json!("a"), 11),
        row("c", "review", "same", "other", Value::Null, 9),
        row("d", "review", "same", "different", Value::Null, 30)
    ]);
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-startup", &startup(records.clone(), 10)),
        Some(json!({"counts":{"expired":2,"exact_duplicates":2,"shared_source":1,"unfinished":1}}))
    );
    let mut bridged = records;
    bridged[3]["scope"] = json!("all");
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-startup", &startup(bridged, 10)),
        Some(json!({"counts":{"expired":2,"exact_duplicates":1,"shared_source":1,"unfinished":1}}))
    );
}

#[test]
fn startup_empty_bodies_and_empty_references_follow_distinct_original_rules() {
    let records = json!([
        row("", "all", "", "", json!(""), 1),
        row("a", "all", "", "", Value::Null, 3652059),
        row("a", "task", "x", "source", json!("a"), 2)
    ]);
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-startup", &startup(records, 2)),
        Some(json!({"counts":{"expired":2,"exact_duplicates":0,"shared_source":1,"unfinished":3}}))
    );
}

#[test]
fn pure_payloads_preserve_exact_strings_and_do_not_normalize_them() {
    let records = json!([
        row("a", "task", "A", "Docs!", Value::Null, 100),
        row("b", "task", "a", "docs", Value::Null, 100)
    ]);
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-startup", &startup(records, 99)),
        Some(json!({"counts":{"expired":0,"exact_duplicates":0,"shared_source":0,"unfinished":0}}))
    );
}

#[test]
fn all_operations_accept_valid_empty_payloads() {
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-live", &live(json!([]))),
        Some(json!({"indices":[]}))
    );
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-replacements", &packet(json!([]))),
        Some(json!({"findings":[]}))
    );
    assert_eq!(
        MemoryUpkeep::evaluate("upkeep-startup", &startup(json!([]), 1)),
        Some(json!({"counts":{"expired":0,"exact_duplicates":0,"shared_source":0,"unfinished":0}}))
    );
}

#[test]
fn protocol_rejects_wrong_version_extra_fields_and_invalid_ordinals() {
    for operation in ["upkeep-live", "upkeep-replacements", "upkeep-startup"] {
        assert!(MemoryUpkeep::evaluate(operation, &json!([])).is_none());
        let mut wrong = packet(json!([]));
        wrong["unicode"] = json!("wrong");
        assert!(MemoryUpkeep::evaluate(operation, &wrong).is_none());
    }
    assert!(MemoryUpkeep::evaluate("unknown", &packet(json!([]))).is_none());
    let mut extra = startup(json!([]), 1);
    extra["extra"] = json!(true);
    assert!(MemoryUpkeep::evaluate("upkeep-startup", &extra).is_none());
    for invalid in [
        json!(0),
        json!(-1),
        json!(3652060),
        json!(true),
        json!(1.0),
        json!(null),
    ] {
        let mut value = startup(json!([]), 1);
        value["today"] = invalid.clone();
        assert!(MemoryUpkeep::evaluate("upkeep-startup", &value).is_none());
        let mut item = row("a", "task", "body", "source", Value::Null, 1);
        item["review"] = invalid;
        assert!(MemoryUpkeep::evaluate("upkeep-startup", &startup(json!([item]), 1)).is_none());
    }
    let mut bad_status = live(json!([]));
    bad_status["statuses"] = json!([1]);
    assert!(MemoryUpkeep::evaluate("upkeep-live", &bad_status).is_none());
}

#[test]
fn malformed_later_rows_decline_without_returning_a_partial_prefix() {
    for bad in [
        json!({"id":"a"}),
        json!({"id":1,"status":"active"}),
        json!({"id":"a","status":"active","extra":1}),
    ] {
        assert!(MemoryUpkeep::evaluate(
            "upkeep-live",
            &live(json!([
                {"id":"a","status":"active"},bad
            ]))
        )
        .is_none());
    }
    for link in [json!(false), json!(1), json!([]), json!({})] {
        assert!(MemoryUpkeep::evaluate(
            "upkeep-replacements",
            &packet(json!([
                {"id":"a","replaces":null},{"id":"b","replaces":link}
            ]))
        )
        .is_none());
    }
    let mut bad = row("a", "task", "body", "source", Value::Null, 1);
    bad["body"] = json!(null);
    assert!(MemoryUpkeep::evaluate("upkeep-startup", &startup(json!([bad]), 1)).is_none());
}
