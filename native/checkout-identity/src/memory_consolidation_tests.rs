use super::*;

fn dup_row(id: &str, scope: &str, tokens: &[&str]) -> Value {
    json!({ "id": id, "scope": scope, "tokens": tokens })
}

fn src_row(id: &str, source: &str) -> Value {
    json!({ "id": id, "source": source })
}

fn payload(records: Value) -> Value {
    json!({ "unicode": MemoryTerms::version(), "records": records })
}

#[test]
fn duplicate_groups_exact_threshold_and_empty_sets() {
    let at_threshold = payload(json!([
        dup_row("b", "task", &["w1", "w2", "w3", "w4"]),
        dup_row("a", "task", &["w1", "w2", "w3", "w4", "w5"]),
        dup_row("c", "task", &["w1", "w2", "w3", "x4"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &at_threshold),
        Some(json!({ "groups": [[1, 0]] }))
    );

    let below_threshold = payload(json!([
        dup_row("a", "task", &["w1", "w2", "w3"]),
        dup_row("b", "task", &["w1", "w2", "w3", "w4"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &below_threshold),
        Some(json!({ "groups": [] }))
    );

    let empty_sets = payload(json!([
        dup_row("a", "task", &[]),
        dup_row("b", "task", &[]),
        dup_row("c", "all", &[]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &empty_sets),
        Some(json!({ "groups": [] }))
    );

    let empty_string_tokens = payload(json!([
        dup_row("second", "task", &[""]),
        dup_row("first", "task", &[""]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &empty_string_tokens),
        Some(json!({ "groups": [[1, 0]] }))
    );
}

#[test]
fn duplicate_groups_transitive_chain_and_scope_bridging() {
    // Endpoints 0 and 1 have Jaccard 3/5 = 0.6 (< 0.8) and are compared before bridge 2.
    let chain = payload(json!([
        dup_row("end-b", "task", &["a", "b", "c", "d"]),
        dup_row("end-a", "task", &["b", "c", "d", "e"]),
        dup_row("bridge", "task", &["a", "b", "c", "d", "e"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &chain),
        Some(json!({ "groups": [[2, 1, 0]] }))
    );

    let disjoint = payload(json!([
        dup_row("a", "task", &["k1", "k2", "k3", "k4"]),
        dup_row("b", "review", &["k1", "k2", "k3", "k4"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &disjoint),
        Some(json!({ "groups": [] }))
    );

    let all_bridge = payload(json!([
        dup_row("t", "task", &["k1", "k2", "k3", "k4"]),
        dup_row("r", "review", &["k1", "k2", "k3", "k4"]),
        dup_row("g", "all", &["k1", "k2", "k3", "k4"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &all_bridge),
        Some(json!({ "groups": [[2, 1, 0]] }))
    );
}

#[test]
fn duplicate_tokens_duplicate_ids_unicode_order_and_tie_groups() {
    let dup_tokens = payload(json!([
        dup_row("a", "task", &["x", "x", "x", "x", "y"]),
        dup_row("b", "task", &["x", "z"]),
        dup_row("d", "review", &["p", "p", "q", "r", "s"]),
        dup_row("c", "review", &["p", "q", "r", "s", "t"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &dup_tokens),
        Some(json!({ "groups": [[3, 2]] }))
    );

    // Unicode scalar order puts U+E000 before U+10000 (unlike UTF-16 code units),
    // and equal IDs retain ascending input index order without deduplication.
    let unicode_and_equal_ids = payload(json!([
        dup_row("\u{10000}", "task", &["m1", "m2", "m3", "m4"]),
        dup_row("same", "task", &["m1", "m2", "m3", "m4"]),
        dup_row("\u{E000}", "task", &["m1", "m2", "m3", "m4"]),
        dup_row("same", "task", &["m1", "m2", "m3", "m4"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &unicode_and_equal_ids),
        Some(json!({ "groups": [[1, 3, 2, 0]] }))
    );

    // Component {0, 2, 3} ends up with root 2 (via (0,3) then (2,3)) while component {1, 4, 5}
    // has root 1; tied ID vectors must keep first-component occurrence order ([0, 2, 3] first).
    let tie_components = payload(json!([
        dup_row("c", "s1", &["a", "b", "c", "d"]),
        dup_row("c", "s2", &["x", "y", "z", "w"]),
        dup_row("a", "s1", &["b", "c", "d", "e"]),
        dup_row("b", "s1", &["a", "b", "c", "d", "e"]),
        dup_row("a", "s2", &["x", "y", "z", "w"]),
        dup_row("b", "s2", &["x", "y", "z", "w"]),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-groups", &tie_components),
        Some(json!({ "groups": [[2, 3, 0], [4, 5, 1]] }))
    );
}

#[test]
fn shared_source_groups_empty_sources_ties_and_lexicographic_order() {
    let shared = payload(json!([
        src_row("b", "z-first-source"),
        src_row("b", "a-second-source"),
        src_row("a", "a-second-source"),
        src_row("a", "z-first-source"),
        src_row("solo", "unique-source"),
        src_row("same", ""),
        src_row("same", ""),
        src_row("a", "prefix-short"),
        src_row("a", "prefix-long"),
        src_row("b", "prefix-long"),
        src_row("c", "prefix-long"),
        src_row("b", "prefix-short"),
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("shared-source-groups", &shared),
        Some(json!({
            "groups": [
                [3, 0],
                [2, 1],
                [7, 11],
                [8, 9, 10],
                [5, 6]
            ]
        }))
    );

    // Exact source matching without extra normalization in Rust.
    let unnormalized = payload(json!([
        src_row("a", "Docs/Guide.md"),
        src_row("b", "docs/guide.md")
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("shared-source-groups", &unnormalized),
        Some(json!({ "groups": [] }))
    );
}

#[test]
fn empty_and_singleton_inputs_succeed_after_validation() {
    for op in ["duplicate-groups", "shared-source-groups"] {
        assert_eq!(
            MemoryConsolidation::evaluate(op, &payload(json!([]))),
            Some(json!({ "groups": [] }))
        );
    }
    assert_eq!(
        MemoryConsolidation::evaluate(
            "duplicate-groups",
            &payload(json!([dup_row("only", "task", &["a"])]))
        ),
        Some(json!({ "groups": [] }))
    );
    assert_eq!(
        MemoryConsolidation::evaluate(
            "shared-source-groups",
            &payload(json!([src_row("only", "")]))
        ),
        Some(json!({ "groups": [] }))
    );
}

#[test]
fn strict_schema_version_row_and_operation_validation_declines() {
    assert!(MemoryConsolidation::evaluate("unknown-op", &payload(json!([]))).is_none());
    assert!(MemoryConsolidation::evaluate("duplicate-groups", &json!([])).is_none());
    assert!(MemoryConsolidation::evaluate(
        "duplicate-groups",
        &json!({ "unicode": "0.0.0", "records": [] })
    )
    .is_none());
    assert!(MemoryConsolidation::evaluate(
        "duplicate-groups",
        &json!({ "unicode": MemoryTerms::version() })
    )
    .is_none());
    assert!(MemoryConsolidation::evaluate(
        "duplicate-groups",
        &json!({ "unicode": MemoryTerms::version(), "records": [], "extra": true })
    )
    .is_none());
    assert!(MemoryConsolidation::evaluate(
        "duplicate-groups",
        &json!({ "unicode": MemoryTerms::version(), "records": {} })
    )
    .is_none());

    // Singleton malformed rows must still decline to None before producing {"groups": []}.
    for bad_dup in [
        json!("not-an-object"),
        json!({ "id": "a", "source": "s" }),
        json!({ "id": "a", "scope": "task" }),
        json!({ "id": "a", "scope": "task", "tokens": [], "extra": 1 }),
        json!({ "id": "a", "scope": "task", "wrong": [] }),
        json!({ "id": 1, "scope": "task", "tokens": [] }),
        json!({ "id": "a", "scope": null, "tokens": [] }),
        json!({ "id": "a", "scope": "task", "tokens": "not-array" }),
        json!({ "id": "a", "scope": "task", "tokens": ["ok", 2] }),
    ] {
        assert!(
            MemoryConsolidation::evaluate("duplicate-groups", &payload(json!([bad_dup]))).is_none()
        );
    }

    for bad_src in [
        json!(123),
        json!({ "id": "a", "scope": "task", "tokens": [] }),
        json!({ "id": "a" }),
        json!({ "id": "a", "source": "s", "extra": "x" }),
        json!({ "id": "a", "wrong": "s" }),
        json!({ "id": null, "source": "s" }),
        json!({ "id": "a", "source": ["s"] }),
    ] {
        assert!(
            MemoryConsolidation::evaluate("shared-source-groups", &payload(json!([bad_src])))
                .is_none()
        );
    }

    // Later malformed row after valid row also declines.
    let mixed = payload(json!([
        dup_row("ok", "task", &["a"]),
        { "id": "bad", "scope": "task", "tokens": [null] }
    ]));
    assert!(MemoryConsolidation::evaluate("duplicate-groups", &mixed).is_none());
}
