use super::*;

fn row(id: &str, replaces: Option<&str>, replaced_by: Option<&str>) -> Value {
    json!({
        "id": id,
        "replaces": replaces,
        "replaced_by": replaced_by,
    })
}

fn request(record_id: &str, records: Vec<Value>) -> Value {
    json!({
        "unicode": MemoryTerms::version(),
        "record_id": record_id,
        "records": records,
    })
}

#[test]
fn linear_chain_from_any_member_returns_newest_first_indices() {
    let records = vec![
        row("node:mid", Some("node:old"), Some("node:new")),
        row("standalone", Some(""), None),
        row("node:old", None, Some("node:mid")),
        row("node:new", Some("node:mid"), Some("")),
    ];
    for id in ["node:old", "node:mid", "node:new"] {
        assert_eq!(
            MemoryHistory::evaluate(&request(id, records.clone())),
            Some(json!({ "indices": [3, 0, 2] }))
        );
    }
    assert_eq!(
        MemoryHistory::evaluate(&request("standalone", records)),
        Some(json!({ "indices": [1] }))
    );
}

#[test]
fn inferred_forward_links_recover_interrupted_predecessor_retire() {
    let records = vec![
        row("first", None, None),
        row("second", Some("first"), Some("")),
        row("third", Some("second"), None),
    ];
    for id in ["first", "second", "third"] {
        assert_eq!(
            MemoryHistory::evaluate(&request(id, records.clone())),
            Some(json!({ "indices": [2, 1, 0] }))
        );
    }
}

#[test]
fn explicit_nonempty_dangling_replaced_by_wins_over_inferred_following() {
    let dangling = vec![
        row("origin", None, Some("missing-next")),
        row("inferred", Some("origin"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("origin", dangling)),
        Some(json!({ "indices": [0] }))
    );
    let empty_explicit = vec![
        row("origin", None, Some("")),
        row("inferred", Some("origin"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("origin", empty_explicit)),
        Some(json!({ "indices": [1, 0] }))
    );
}

#[test]
fn branches_follow_explicit_winner_or_last_ordered_inferred_follower() {
    let inferred = vec![
        row("root", None, None),
        row("branch_a", Some("root"), None),
        row("leaf_a", Some("branch_a"), None),
        row("branch_b", Some("root"), None),
        row("leaf_b", Some("branch_b"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("root", inferred.clone())),
        Some(json!({ "indices": [4, 3, 0] }))
    );
    assert_eq!(
        MemoryHistory::evaluate(&request("branch_a", inferred)),
        Some(json!({ "indices": [2, 1, 0] }))
    );

    let explicit = vec![
        row("root", None, Some("branch_a")),
        row("branch_a", Some("root"), None),
        row("leaf_a", Some("branch_a"), None),
        row("branch_b", Some("root"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("root", explicit)),
        Some(json!({ "indices": [2, 1, 0] }))
    );
}

#[test]
fn duplicate_ids_use_last_row_index_and_first_insertion_order_for_forks() {
    // fork_a appears after fork_b in raw input due to index 2, but keeps its
    // first insertion slot (before fork_b) in by_id.values(), so fork_b wins.
    let records = vec![
        row("fork_a", Some("other"), None),
        row("fork_b", Some("root"), None),
        row("fork_a", Some("root"), None),
        row("root", None, None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("root", records.clone())),
        Some(json!({ "indices": [1, 3] }))
    );
    assert_eq!(
        MemoryHistory::evaluate(&request("fork_a", records)),
        Some(json!({ "indices": [2, 3] }))
    );

    // Reversing first insertion slots flips the inferred fork winner to fork_a
    // even though fork_b is updated last in raw input at index 2.
    let reversed = vec![
        row("fork_b", Some("root"), None),
        row("fork_a", Some("root"), None),
        row("fork_b", Some("root"), None),
        row("root", None, None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("root", reversed.clone())),
        Some(json!({ "indices": [1, 3] }))
    );
    assert_eq!(
        MemoryHistory::evaluate(&request("fork_b", reversed)),
        Some(json!({ "indices": [2, 3] }))
    );
}

#[test]
fn cycles_terminate_in_both_forward_and_backward_walks() {
    let self_loop = vec![row("solo", Some("solo"), Some("solo"))];
    assert_eq!(
        MemoryHistory::evaluate(&request("solo", self_loop)),
        Some(json!({ "indices": [0] }))
    );

    let mutual = vec![
        row("a", Some("b"), Some("b")),
        row("b", Some("a"), Some("a")),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("a", mutual)),
        Some(json!({ "indices": [1, 0] }))
    );

    let inferred_cycle = vec![
        row("a", Some("c"), None),
        row("b", Some("a"), None),
        row("c", Some("b"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("a", inferred_cycle)),
        Some(json!({ "indices": [2, 1, 0] }))
    );

    let backward_lasso = vec![
        row("n1", Some("n2"), Some("n2")),
        row("n2", Some("n1"), Some("n3")),
        row("n3", Some("n2"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("n3", backward_lasso)),
        Some(json!({ "indices": [2, 1, 0] }))
    );
}

#[test]
fn missing_predecessor_stops_backward_walk_cleanly() {
    let records = vec![
        row("mid", Some("missing-oldest"), None),
        row("latest", Some("mid"), None),
    ];
    assert_eq!(
        MemoryHistory::evaluate(&request("mid", records)),
        Some(json!({ "indices": [1, 0] }))
    );
}

#[test]
fn backward_walk_caps_at_twenty_indices_after_longer_forward_walk() {
    let mut records = Vec::new();
    for i in 0..25 {
        let id = format!("r{i}");
        let prev = (i > 0).then(|| format!("r{}", i - 1));
        records.push(json!({
            "id": id,
            "replaces": prev,
            "replaced_by": Value::Null,
        }));
    }
    let expected: Vec<usize> = (5..25).rev().collect();
    assert_eq!(
        MemoryHistory::evaluate(&request("r0", records)),
        Some(json!({ "indices": expected }))
    );
}

#[test]
fn malformed_schema_unicode_types_and_missing_target_decline() {
    let valid_row = row("a", None, None);
    assert!(MemoryHistory::evaluate(&json!(null)).is_none());
    assert!(MemoryHistory::evaluate(&json!([])).is_none());
    assert!(MemoryHistory::evaluate(&request("a", vec![])).is_none());
    assert!(MemoryHistory::evaluate(&request("missing", vec![valid_row.clone()])).is_none());

    let mut bad_unicode = request("a", vec![valid_row.clone()]);
    bad_unicode["unicode"] = json!("0.0.0");
    assert!(MemoryHistory::evaluate(&bad_unicode).is_none());

    let mut extra_top = request("a", vec![valid_row.clone()]);
    extra_top["extra"] = json!(true);
    assert!(MemoryHistory::evaluate(&extra_top).is_none());

    assert!(MemoryHistory::evaluate(&json!({
        "unicode": MemoryTerms::version(),
        "record_id": "a",
        "other": [valid_row.clone()],
    }))
    .is_none());

    assert!(MemoryHistory::evaluate(&json!({
        "unicode": MemoryTerms::version(),
        "record_id": 123,
        "records": [valid_row.clone()],
    }))
    .is_none());

    for bad_row in [
        json!(null),
        json!({"id": "b", "replaces": null}),
        json!({"id": "b", "replaces": null, "replaced_by": null, "body": "extra"}),
        json!({"id": "b", "replaces": null, "unknown": null}),
        json!({"id": null, "replaces": null, "replaced_by": null}),
        json!({"id": "b", "replaces": 1, "replaced_by": null}),
        json!({"id": "b", "replaces": null, "replaced_by": false}),
        json!({"id": "b", "replaces": [], "replaced_by": null}),
    ] {
        assert!(MemoryHistory::evaluate(&request("a", vec![valid_row.clone(), bad_row])).is_none());
    }
}
