use super::*;

fn capture() -> Value {
    json!({"unicode":MemoryTerms::version(),"today":"2026-11-17","review_on":"2099-01-01",
        "body":"  한글 body  ","source":" note ","scope":"task",
        "applies_when":" ready ","not_when":"  "})
}

#[test]
fn capture_analysis_reuses_binding_and_preserves_scalar_error_precedence() {
    let mut value = capture();
    value["analysis"] = json!({"question":" Why 한글? ","context":" Keep NOT X "});
    let result = MemoryRecord::capture_inputs(&value).unwrap();
    assert_eq!(
        result["analysis"],
        json!({"binding":{"question":"Why 한글?","context":"Keep NOT X"}})
    );
    assert_eq!(result.as_object().unwrap().len(), 4);
    value["analysis"]["question"] = json!("");
    assert_eq!(
        MemoryRecord::capture_inputs(&value).unwrap()["analysis"],
        json!({"invalid":true})
    );
    value["body"] = json!("");
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({"invalid":"body"}))
    );
}

#[test]
fn capture_analysis_declines_open_or_combined_digest_schemas() {
    for analysis in [
        json!(null),
        json!([]),
        json!(true),
        json!({"question":"q"}),
        json!({"question":"q","context":1}),
        json!({"question":"q","context":"c","extra":"x"}),
    ] {
        let mut value = capture();
        value["analysis"] = analysis;
        assert!(MemoryRecord::capture_inputs(&value).is_none());
    }
    let mut value = capture();
    value["analysis"] = json!({"question":"q","context":"c"});
    value["digest"] = json!(true);
    assert!(MemoryRecord::capture_inputs(&value).is_none());
}

#[test]
fn capture_analysis_keeps_raw_length_and_printability_rules() {
    for (question, valid) in [
        ("한".repeat(300), true),
        ("한".repeat(301), false),
        (" q ".to_owned(), true),
        ("q\n".to_owned(), false),
        ("\u{85}q".to_owned(), false),
    ] {
        let mut value = capture();
        value["analysis"] = json!({"question":question,"context":"c"});
        let analysis = MemoryRecord::capture_inputs(&value).unwrap()["analysis"].clone();
        assert_eq!(analysis.get("binding").is_some(), valid);
    }
    let mut value = capture();
    value["analysis"] = json!({"question":"","context":""});
    assert_eq!(
        MemoryRecord::capture_inputs(&value).unwrap()["analysis"],
        json!({"binding":null})
    );
}

#[test]
fn capture_digest_opt_in_matches_captured_python_canonical_bytes() {
    let mut value = capture();
    value["digest"] = json!(true);
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({
        "body":"한글 body","source":"note","conditions":{"applies_when":"ready"},
        "digest":"8a144e1b51e54cc11ca958ba50b48c8f199da2ca90cd34b97863698618bdc41e"}))
    );
    value["body"] = json!("");
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({"invalid":"body"}))
    );
}

#[test]
fn capture_digest_requires_literal_true_and_closed_schema() {
    for flag in [json!(false), json!(1), json!("true"), json!(null)] {
        let mut value = capture();
        value["digest"] = flag;
        assert!(MemoryRecord::capture_inputs(&value).is_none());
    }
    let mut value = capture();
    value["digest"] = json!(true);
    value["extra"] = json!(true);
    assert!(MemoryRecord::capture_inputs(&value).is_none());
}

#[test]
fn capture_digest_uses_conditions_and_scope_but_keeps_legacy_response_closed() {
    let original = capture();
    let legacy = MemoryRecord::capture_inputs(&original).unwrap();
    assert_eq!(legacy.as_object().unwrap().len(), 3);
    let mut value = original;
    value["digest"] = json!(true);
    let original_digest = MemoryRecord::capture_inputs(&value).unwrap()["digest"].clone();
    for (key, text) in [
        ("scope", "all"),
        ("not_when", "except"),
        ("review_on", "2099-01-02"),
    ] {
        let mut value = value.clone();
        value[key] = json!(text);
        let digest = MemoryRecord::capture_inputs(&value).unwrap()["digest"].clone();
        assert_ne!(original_digest, digest);
    }
}

#[test]
fn capture_normalizes_python_whitespace_and_preserves_unicode_character_limits() {
    let mut value = capture();
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({
        "body":"한글 body","source":"note","conditions":{"applies_when":"ready"}}))
    );
    value["body"] = json!(format!("\u{001c}{}\u{0085}", "한".repeat(500)));
    value["source"] = json!("é".repeat(200));
    value["not_when"] = json!("🚀".repeat(160));
    assert!(MemoryRecord::capture_inputs(&value)
        .unwrap()
        .get("invalid")
        .is_none());
    for (key, count, code) in [
        ("body", 501, "body"),
        ("source", 201, "source"),
        ("not_when", 161, "conditions"),
    ] {
        let mut value = value.clone();
        value[key] = json!("한".repeat(count));
        assert_eq!(
            MemoryRecord::capture_inputs(&value),
            Some(json!({"invalid":code}))
        );
    }
}

#[test]
fn capture_reports_original_validation_order_and_leaves_bad_dates_to_python() {
    let mut value = capture();
    value["body"] = json!("");
    value["source"] = json!("");
    value["scope"] = json!("bad scope");
    value["review_on"] = json!("bad date");
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({"invalid":"body"}))
    );
    value["body"] = json!("body");
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({"invalid":"source"}))
    );
    value["source"] = json!("source");
    assert_eq!(
        MemoryRecord::capture_inputs(&value),
        Some(json!({"invalid":"scope"}))
    );
    value["scope"] = json!("task");
    assert!(MemoryRecord::capture_inputs(&value).is_none());
    for day in ["2026-11-17", "0001-01-01"] {
        value["review_on"] = json!(day);
        assert_eq!(
            MemoryRecord::capture_inputs(&value),
            Some(json!({"invalid":"review"}))
        );
    }
    for day in ["20261118", "2026-W47-3", "1900-02-29", "2099-04-31"] {
        value["review_on"] = json!(day);
        assert!(MemoryRecord::capture_inputs(&value).is_none());
    }
}

#[test]
fn capture_declines_open_schemas_and_rejects_nonprintable_content() {
    for key in ["body", "source", "applies_when", "not_when"] {
        let mut value = capture();
        value[key] = json!("a\nb");
        let code = if key == "body" || key == "source" {
            key
        } else {
            "conditions"
        };
        assert_eq!(
            MemoryRecord::capture_inputs(&value),
            Some(json!({"invalid":code}))
        );
    }
    for (key, entry) in [
        ("extra", json!(true)),
        ("scope", json!(null)),
        ("today", json!("bad")),
        ("unicode", json!("unknown")),
        ("not_when", json!([])),
    ] {
        let mut value = capture();
        value[key] = entry;
        assert!(MemoryRecord::capture_inputs(&value).is_none());
    }
}
