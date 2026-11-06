use super::*;
fn advice(gates: &[&str]) -> Value {
    let payload=Py::parse(&serde_json::to_string(&json!({"route":{"gates":gates,"command":"small-change","required_docs":["common/skills/small-change/SKILL.md"]}})).unwrap()).unwrap();
    serde_json::from_str(
        &NextAdvice::render(
            Path::new("/project"),
            Path::new("/run/preflight.json"),
            &payload,
            &Verification::default(),
            "json",
            Path::new("/launcher"),
        )
        .unwrap(),
    )
    .unwrap()
}
#[test]
fn all_active_decisions_leave_results_to_agent() {
    for (gates, expected) in [
        (vec![], "finish"),
        (vec!["commit readiness"], "finish"),
        (vec!["review hook"], "review"),
        (vec!["tests", "review hook"], "record_pre_review_gates"),
        (vec!["retrospective check"], "record_closeout_gates"),
    ] {
        let result = advice(&gates);
        assert_eq!(result["next_step"], expected);
        assert_eq!(result["loaded_skills"], json!(["agent_operating_skill"]));
    }
    let result = advice(&["tests", "review hook"]);
    assert!(result["copyable_command"]
        .as_str()
        .unwrap()
        .contains("<SUCCESS or FAIL>"));
    assert!(!result["copyable_command"]
        .as_str()
        .unwrap()
        .contains("\"status\":\"SUCCESS\""));
}
#[test]
fn unknown_gate_keeps_generic_template_and_order() {
    let result = advice(&["한글 gate"]);
    assert_eq!(result["next_step"], "record_closeout_gates");
    assert_eq!(result["template_lines"][1],"fill-in template for 한글 gate: {\"gate\":\"한글 gate\",\"status\":\"SUCCESS\",\"fields\":{}}");
}
#[test]
fn malformed_route_shapes_decline() {
    for text in [
        "[]",
        r#"{"route":[]}"#,
        r#"{"route":{"gates":{}}}"#,
        r#"{"route":{"required_docs":false}}"#,
    ] {
        assert!(NextAdvice::render(
            Path::new("/p"),
            Path::new("/r/preflight.json"),
            &Py::parse(text).unwrap(),
            &Verification::default(),
            "json",
            Path::new("/l")
        )
        .is_none());
    }
}
