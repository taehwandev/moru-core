use super::*;
use crate::memory_terms::MemoryTerms;

fn row(id: &str, body: &str) -> Value {
    json!({"id":id,"body":body,"source":"checked","review_on":"2099-01-01",
        "status":"active","scope":"task"})
}

fn payload(records: Value) -> Value {
    json!({"unicode":MemoryTerms::version(),"scope":"task","today":"2026-01-01",
        "context":"","records":records,"limits":{"items":3,"chars":1200,"previous":160}})
}

#[test]
fn projected_key_order_and_last_duplicate_predecessor_match_python() {
    let mut first = row("old", "first");
    first["status"] = json!("retired");
    let mut last = row("old", "😀😀😀😀");
    last["status"] = json!("retired");
    let mut current = row("new", "body");
    current["replaces"] = json!("old");
    current["applies_when"] = json!("condition");
    current["not_when"] = json!("exception");
    let mut request = payload(json!([first, last, current]));
    request["limits"]["previous"] = json!(3);
    let result = MemoryContext::evaluate(&request).unwrap();
    let item = &result["items"][0];
    assert_eq!(item["previously"], "😀😀…");
    assert_eq!(
        item.as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        [
            "id",
            "body",
            "source",
            "review_on",
            "applies_when",
            "not_when",
            "previously"
        ]
    );
}

#[test]
fn python_spacing_and_scalar_length_control_exact_budget_boundaries() {
    let body = "한글😀\n\t\\\"";
    let golden =
        r#"{"id": "b", "body": "한글😀\n\t\\\"", "source": "checked", "review_on": "2099-01-01"}"#;
    let size = golden.chars().count();
    let mut request = payload(json!([
        row("a", &"x".repeat(2000)),
        row("b", body),
        row("c", body)
    ]));
    request["limits"]["chars"] = json!(size);
    assert_eq!(
        MemoryContext::evaluate(&request).unwrap()["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        MemoryContext::evaluate(&request).unwrap()["items"][0]["id"],
        "b"
    );
    request["limits"]["chars"] = json!(size - 1);
    assert_eq!(MemoryContext::evaluate(&request), Some(json!({"items":[]})));
    request["limits"]["chars"] = json!(2 * size);
    assert_eq!(
        MemoryContext::evaluate(&request).unwrap()["items"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn empty_and_zero_item_requests_keep_selection_validation() {
    assert_eq!(
        MemoryContext::evaluate(&payload(json!([]))),
        Some(json!({"items":[]}))
    );
    let mut request = payload(json!([row("a", "body")]));
    request["limits"]["items"] = json!(0);
    assert_eq!(MemoryContext::evaluate(&request), Some(json!({"items":[]})));
    request["records"][0]["review_on"] = json!("invalid");
    assert!(MemoryContext::evaluate(&request).is_none());
}

#[test]
fn source_backed_or_custom_rendering_profiles_decline_atomically() {
    let base = payload(json!([row("a", "body")]));
    for (field, value) in [
        ("source_files", json!([{"path":"never-read","blob":"old"}])),
        ("source_files", Value::Null),
        ("body", json!(1)),
        ("applies_when", json!(false)),
    ] {
        let mut request = base.clone();
        request["records"][0][field] = value;
        assert!(MemoryContext::evaluate(&request).is_none(), "{field}");
    }
    for (field, value) in [
        ("items", json!(true)),
        ("chars", json!(-1)),
        ("previous", json!(0)),
        ("extra", json!(0)),
    ] {
        let mut request = base.clone();
        request["limits"][field] = value;
        assert!(MemoryContext::evaluate(&request).is_none(), "{field}");
    }
}

#[test]
fn empty_predecessor_ids_and_optional_empty_strings_are_preserved() {
    let mut old = row("", "empty id");
    old["status"] = json!("retired");
    let mut current = row("new", "body");
    current["applies_when"] = json!("");
    let result = MemoryContext::evaluate(&payload(json!([old, current]))).unwrap();
    assert_eq!(result["items"][0]["previously"], "empty id");
    assert_eq!(result["items"][0]["applies_when"], "");
}
