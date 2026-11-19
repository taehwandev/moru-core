use super::*;

fn plan_payload(records: Value) -> Value {
    json!({"unicode":MemoryTerms::version(),"records":records,
        "review":{"today":"2026-11-16","horizon":"2026-11-30",
                  "statuses":["active","pending","approved"]}})
}

#[test]
fn complete_report_plan_keeps_original_and_live_relative_indices_separate() {
    let input = plan_payload(json!([
        {"id":"b","status":"active","scope":"task","body":"same","source":"S",
         "review":"2026-11-16","replaces":"a"},
        {"id":"a","status":"pending","scope":"all","body":"same","source":"S",
         "review":"2026-11-15","replaces":null},
        {"id":"c","status":"approved","scope":"task","body":"other","source":"T",
         "review":"2026-11-17","replaces":null},
        {"id":"x","status":"retired","scope":"all","body":"same","source":"S",
         "review":"invalid","replaces":null},
        {"id":"a","status":"active","scope":"task","body":"same","source":"S",
         "review":"2099-01-01","replaces":null}
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({
            "review":{"live":[1,4,0,2],"expired":[0],"expiring":[2]},
            "relations":{"duplicates":[[0,1,2]],"shared_sources":[[0,1,2]],
                "findings":[{"index":0,"replacements":[2]},{"index":1,"replacements":[2]}]}
        }))
    );
}

#[test]
fn complete_report_renders_review_entries_only_when_requested() {
    let mut input = plan_payload(json!([
        {"id":"b","status":"active","scope":"task","body":"second","source":"S2",
         "review":"2026-11-17","replaces":"a"},
        {"id":"a","status":"active","scope":"all","body":"한글","source":"S1",
         "review":"2026-11-16","replaces":null}
    ]));
    input["review"]["render_days"] = json!(14);
    let result = MemoryConsolidation::evaluate("report-text-groups", &input).unwrap();
    assert_eq!(
        result["replacement_entries"],
        json!([
            {"id":"a","scope":"all","body":"한글","source":"S1","review_on":"2026-11-16",
                "reason":"a live record replaces this one; `retire` it to finish the interrupted replacement",
                "replaced_by":["b"]}
        ])
    );
    assert_eq!(
        result["date_entries"],
        json!({
            "expired":[{"id":"a","scope":"all","body":"한글","source":"S1","review_on":"2026-11-16",
                "reason":"review date reached; recheck the source, then renew with `capture --replaces` and a new date, or `retire`"}],
            "expiring":[{"id":"b","scope":"task","body":"second","source":"S2","review_on":"2026-11-17",
                "reason":"review date within 14 days; renew or retire ahead of time"}]
        })
    );
    for invalid in [json!(true), json!(-1), json!(null), json!("14")] {
        input["review"]["render_days"] = invalid;
        assert!(MemoryConsolidation::evaluate("report-text-groups", &input).is_none());
    }
}

#[test]
fn complete_report_empty_shape_and_closed_calendar_are_preserved() {
    let mut input = plan_payload(json!([]));
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({
            "review":{"live":[],"expired":[],"expiring":[]},
            "relations":{"duplicates":[],"shared_sources":[],"findings":[]}
        }))
    );
    for review in [
        json!(null),
        json!({}),
        json!({"today":"2026-02-30","horizon":"2026-11-30","statuses":[]}),
        json!({"today":"2026-11-16","horizon":"2026-11-30","statuses":"active"}),
        json!({"today":"2026-11-16","horizon":"2026-11-30","statuses":[],"extra":true}),
    ] {
        input["review"] = review;
        assert!(MemoryConsolidation::evaluate("report-text-groups", &input).is_none());
    }
}

#[test]
fn complete_report_declines_malformed_rows_without_partial_decisions() {
    let row = json!({"id":"a","status":"active","scope":"task","body":"same",
        "source":"S","review":"2026-11-16","replaces":null});
    for (key, value) in [
        ("source", Value::Null),
        ("status", json!(true)),
        ("replaces", json!(3)),
        ("review", json!("bad date")),
        ("extra", json!(true)),
    ] {
        let mut invalid = row.clone();
        invalid[key] = value;
        assert!(MemoryConsolidation::evaluate(
            "report-text-groups",
            &plan_payload(json!([row, invalid]))
        )
        .is_none());
    }
}

#[test]
fn report_relations_preserve_duplicate_ids_cycles_and_sorted_replacers() {
    let input = json!({"unicode":MemoryTerms::version(),"relations":true,"records":[
        {"id":"b","scope":"task","body":"X!","source":"Guide!","replaces":"a"},
        {"id":"a","scope":"all","body":"x","source":"guide","replaces":null},
        {"id":"a","scope":"review","body":"other","source":"else","replaces":"a"},
        {"id":"c","scope":"review","body":"x","source":"docs","replaces":"missing"}
    ]});
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({
            "duplicates":[[1,0,3]],"shared_sources":[[1,0]],
            "findings":[{"index":1,"replacements":[2,0]},{"index":2,"replacements":[2,0]}]
        }))
    );
}

#[test]
fn report_relations_keep_legacy_empty_shape_and_require_literal_opt_in() {
    let mut input = payload(json!([]));
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({"duplicates":[],"shared_sources":[]}))
    );
    input["relations"] = json!(true);
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({"duplicates":[],"shared_sources":[],"findings":[]}))
    );
    for flag in [json!(false), json!(1), json!("true"), Value::Null] {
        input["relations"] = flag;
        assert!(MemoryConsolidation::evaluate("report-text-groups", &input).is_none());
    }
}

#[test]
fn report_relations_reject_invalid_links_without_partial_results() {
    for link in [json!(false), json!(3), json!([]), json!({})] {
        let input = json!({"unicode":MemoryTerms::version(),"relations":true,"records":[
            {"id":"b","scope":"task","body":"x","source":"s","replaces":"a"},
            {"id":"a","scope":"task","body":"x","source":"s","replaces":link}
        ]});
        assert!(MemoryConsolidation::evaluate("report-text-groups", &input).is_none());
    }
    let input = json!({"unicode":MemoryTerms::version(),"relations":true,
        "records":[{"id":"a","scope":"task","body":"x","source":"s"}]});
    assert!(MemoryConsolidation::evaluate("report-text-groups", &input).is_none());
}

#[test]
fn report_groups_keep_independent_normalization_and_transitive_scope_rules() {
    let input = payload(json!([
        {"id":"c","scope":"review","body":"A b c d e f","source":"Docs!"},
        {"id":"a","scope":"task","body":"a b c d","source":"docs"},
        {"id":"b","scope":"all","body":"a b c d e","source":"Other"}
    ]));
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &input),
        Some(json!({"duplicates":[[1,2,0]],"shared_sources":[[1,0]]}))
    );
}

#[test]
fn empty_report_groups_have_no_components() {
    assert_eq!(
        MemoryConsolidation::evaluate("report-text-groups", &payload(json!([]))),
        Some(json!({"duplicates":[],"shared_sources":[]}))
    );
}

#[test]
fn report_groups_decline_closed_profile_errors_without_partial_output() {
    for row in [
        json!({"id":"a","scope":"task","body":"x","source":null}),
        json!({"id":"a","scope":false,"body":"x","source":"s"}),
        json!({"id":"a","scope":"task","body":3,"source":"s"}),
        json!({"scope":"task","body":"x","source":"s"}),
        json!({"id":"a","scope":"task","body":"x","source":"s","extra":1}),
    ] {
        assert!(MemoryConsolidation::evaluate(
            "report-text-groups",
            &payload(json!([
                {"id":"valid","scope":"task","body":"x","source":"s"}, row
            ]))
        )
        .is_none());
    }
    assert!(MemoryConsolidation::evaluate(
        "report-text-groups",
        &json!({"unicode":"unsupported","records":[]})
    )
    .is_none());
}

#[test]
fn raw_duplicate_normalization_keeps_python_lower_unicode_and_empty_rules() {
    for (left, right, matched) in [
        ("ΟΣ!", "ος", true),
        ("ABC_DEF, 한글\u{a0}é", "abc_def 한글 é", true),
        ("Straße", "STRASSE", false),
        ("e\u{301}", "é", false),
        ("İ", "i", true),
        ("!!!", "???", false),
        ("\u{1c}a\tb", "a b", true),
    ] {
        let input = payload(json!([{"id":"b","scope":"task","body":left},
            {"id":"a","scope":"task","body":right}]));
        let expected = if matched {
            json!({"groups":[[1,0]]})
        } else {
            json!({"groups":[]})
        };
        assert_eq!(
            MemoryConsolidation::evaluate("duplicate-text-groups", &input),
            Some(expected),
            "{left:?}"
        );
    }
}

#[test]
fn raw_source_normalization_groups_empty_values_and_preserves_duplicate_stability() {
    let input = payload(json!([{"id":"x","source":"ΟΣ!"},{"id":"a","source":"!!!"},
        {"id":"x","source":"ος"},{"id":"b","source":""}]));
    assert_eq!(
        MemoryConsolidation::evaluate("shared-source-text-groups", &input),
        Some(json!({"groups":[[1,3],[0,2]]}))
    );
}

#[test]
fn raw_duplicate_groups_reuse_transitive_all_scope_bridges() {
    let input = payload(json!([{"id":"c","scope":"review","body":"A b c d e f"},
        {"id":"a","scope":"task","body":"a b c d"},{"id":"b","scope":"all","body":"a b c d e"}]));
    assert_eq!(
        MemoryConsolidation::evaluate("duplicate-text-groups", &input),
        Some(json!({"groups":[[1,2,0]]}))
    );
}

#[test]
fn raw_empty_and_closed_profiles_decline_invalid_types_without_partial_groups() {
    for operation in ["duplicate-text-groups", "shared-source-text-groups"] {
        assert_eq!(
            MemoryConsolidation::evaluate(operation, &payload(json!([]))),
            Some(json!({"groups":[]}))
        );
    }
    for record in [
        json!({"id":"a","scope":"task","body":1}),
        json!({"id":"a","scope":"task","body":"x","extra":true}),
    ] {
        assert!(
            MemoryConsolidation::evaluate("duplicate-text-groups", &payload(json!([record])))
                .is_none()
        );
    }
    assert!(MemoryConsolidation::evaluate(
        "shared-source-text-groups",
        &payload(json!([{"id":"a","source":null}]))
    )
    .is_none());
}

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
