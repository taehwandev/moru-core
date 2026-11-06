use super::*;
#[test]
fn model_and_location_coerce_nested_values() {
    assert_eq!(
        Renderer::render(
            r#"{"model":{"display_name":true},"cwd":{"x":null}}"#,
            "",
            false
        ),
        Some("True · {'x': None}".into())
    );
    assert_eq!(
        Renderer::render(
            r#"{"model":{"display_name":[],"id":[true,null]},"workspace":{"project_dir":false,"current_dir":[1,"x"]}}"#,
            "",
            false
        ),
        Some("[True, None] · [1, 'x']".into())
    );
    assert_eq!(
        Renderer::render(
            r#"{"model":{"id":{"z":0,"a":1,"z":2}},"cwd":NaN}"#,
            "",
            false
        ),
        Some("{'z': 2, 'a': 1} · nan".into())
    );
    assert_eq!(
        Renderer::render(r#"{"model":42,"cwd":false}"#, "", false),
        Some(String::new())
    );
}
#[test]
fn big_integer_model_is_exact_and_quota_overflow_declines() {
    let integer = "9".repeat(400);
    assert_eq!(
        Renderer::render(&format!("{{\"model\":{{\"id\":{integer}}}}}"), "", false),
        Some(integer.clone())
    );
    assert!(Renderer::render(
        &format!("{{\"rate_limits\":{{\"unknown\":{{\"percent\":{integer}}}}}}}"),
        "",
        false
    )
    .is_none());
    assert!(Renderer::render(
        &format!(
            "{{\"rate_limits\":{{\"primary\":{{\"percent\":1,\"window_minutes\":{integer}}}}}}}"
        ),
        "",
        false
    )
    .is_none());
}
#[test]
fn quota_kind_collections_and_nonfinite_json_values() {
    let result=Renderer::render(r#"{"rate_limits":[{"kind":["weekly"],"percent":20},{"kind":true,"window_minutes":300,"percent":1}]}"#,"",false).unwrap();
    assert!(result.starts_with("5h "));
    assert!(result.contains("7d "));
    assert!(result.contains("80%"));
    assert_eq!(
        Renderer::render(
            r#"{"rate_limits":{"unknown":{"percent":NaN}},"model":{"id":Infinity}}"#,
            "",
            false
        ),
        Some("inf".into())
    );
    assert!(
        Renderer::render(r#"{"rate_limits":{"primary":{"percent":NaN}}}"#, "", false).is_none()
    );
}
#[test]
fn syntax_errors_are_empty_but_unsupported_values_still_defer() {
    assert_eq!(Renderer::render("{", "", false), Some(String::new()));
    assert_eq!(
        Renderer::render(r#"{"model":"\q"}"#, "", false),
        Some(String::new())
    );
    assert!(Renderer::render(r#"{"model":{"id":"\ud800"}}"#, "", false).is_none());
}
