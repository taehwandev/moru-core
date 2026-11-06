use super::*;

fn base() -> Value {
    Py::parse(
        r#"{"schemaVersion":4,"meta":{"fileKey":"f","startNodeId":"s","generatedAt":"now"},
      "screens":[],"flowEdges":[],"flowInteractions":[],"designTokens":{"variables":[]},
      "components":[],"componentBlueprints":[],"colors":[],"gradients":[],"textStyles":[],
      "textRuns":[],"effects":[],"layoutMetrics":{},"layoutNodes":[],"assetCandidates":[],
      "assetInventory":[],"warnings":[],"implementationInventory":{}}"#,
    )
    .unwrap()
}
fn set(value: &mut Value, key: &str, json: &str) {
    let Value::Object(object) = value else {
        panic!("fixture must be an object")
    };
    object.insert(key.to_owned(), Py::parse(json).unwrap());
}

#[test]
fn valid_summary_float_schema_and_unhashable_membership() {
    let mut summary = base();
    assert_eq!(FigmaValidation::validate(&summary), Some(Vec::new()));
    set(&mut summary, "schemaVersion", "4.0");
    assert_eq!(
        FigmaValidation::validate(&summary),
        Some(vec!["schemaVersion invalid: 4.0".into()])
    );
    set(&mut summary, "assetCandidates", r#"[{"id":[]}]"#);
    assert!(FigmaValidation::validate(&summary).is_none());
    assert!(
        FigmaValidation::validate(&Py::parse(r#"{"flowEdges":[{"fromNodeId":{}}]}"#).unwrap())
            .is_none()
    );
}

#[test]
fn paints_keep_insertion_order_after_visibility_before_stroke() {
    let nodes = Py::parse(
        r#"[{"id":0,"visible":2,"opacity":true,"effectiveVisible":true,
        "visibilityReasons":["unexpected"],"renderedPaints":{"z":[{}],"a":0},
        "strokeWeight":-1,"absoluteBoundingBox":{}}]"#,
    )
    .unwrap();
    let mut errors = Vec::new();
    let ids = layout::validate(&mut errors, &nodes, true);
    assert!(ids.all.contains("0"));
    assert_eq!(
        errors,
        vec![
            "layoutNodes[0].id missing",
            "layoutNodes[0].type missing",
            "layoutNodes[0].visible not a boolean: 2",
            "layoutNodes[0].opacity out of [0,1]: True",
            "layoutNodes[0].visibilityReasons present for rendered node",
            "layoutNodes[0].renderedPaints.z[0].type missing",
            "layoutNodes[0].renderedPaints.a is not a list",
            "layoutNodes[0].strokeWeight invalid: -1",
            "layoutNodes[0].absoluteBoundingBox malformed"
        ]
    );
}

#[test]
fn inventory_partition_and_worklist_leaks_preserve_order() {
    let mut summary = base();
    set(
        &mut summary,
        "layoutNodes",
        r#"[{"id":"x","type":"FRAME","effectiveVisible":false,"visibilityReasons":["hidden"]}]"#,
    );
    set(
        &mut summary,
        "implementationInventory",
        r#"{"renderedNodeIds":["x"],"excludedNodes":[{"id":"x","reasons":["hidden"]}]}"#,
    );
    set(&mut summary, "assetCandidates", r#"[{"id":"x"}]"#);
    set(&mut summary, "flowEdges", r#"[{"fromNodeId":"x"}]"#);
    set(&mut summary, "flowInteractions", r#"[{"fromNodeId":"x"}]"#);
    set(
        &mut summary,
        "components",
        r#"[{"componentId":"c","usageCount":1,"instanceNodeIds":["x","x"]}]"#,
    );
    assert_eq!(
        FigmaValidation::validate(&summary).unwrap(),
        vec![
            "implementationInventory rendered and excluded node ids overlap: x",
            "implementationInventory.renderedNodeIds disagrees with effectiveVisible",
            "assetCandidates includes excluded node id: x",
            "flowEdges includes excluded source node id: x",
            "flowInteractions includes excluded source node id: x",
            "components[0].instanceNodeIds includes excluded node ids: x"
        ]
    );
}

#[test]
fn regex_dollar_and_exact_number_categories() {
    for text in ["#ABCDEF", "#01234567", "#ABCDEF\n"] {
        assert!(hex(&Value::String(text.into())));
    }
    for text in ["#abcdef", "#ABCDEF\n\n", "#ABCDEF\r", "#ABCDE"] {
        assert!(!hex(&Value::String(text.into())));
    }
    let huge = Py::parse(&"9".repeat(400)).unwrap();
    assert!(integer_at_least(&huge, 4));
    assert!(numeric(&huge).unwrap() > 0.0);
    assert!(!unit(&huge));
    assert!(!unit(&Py::parse("NaN").unwrap()));
    assert_eq!(numeric(&Value::Bool(true)), None);
}
