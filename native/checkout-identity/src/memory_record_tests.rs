use super::*;

fn capture() -> Value {
    json!({"unicode":MemoryTerms::version(),"today":"2026-11-17","review_on":"2099-01-01",
        "body":"  한글 body  ","source":" note ","scope":"task",
        "applies_when":" ready ","not_when":"  "})
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
