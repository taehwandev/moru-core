use super::*;
fn text(value: &Value) -> String {
    PythonJson::string(value)
}
#[test]
fn coverage_tracks_unprinted_fields_truthiness_and_overlapping_warnings() {
    let value = PythonJson::parse(r#"{
      "layoutNodes":[null,{}, {"opacity":0,"constraints":false,"renderedPaints":[0]}],
      "implementationInventory":{"renderedNodeIds":["a","a",3],"excludedNodes":[{},null]},
      "assetCandidates":[{"id":"x","assetPath":"","imageRefs":["image"]},{"id":"x","assetPath":"duplicate"},{"id":"y","assetPath":1,"renderFallbackIds":[null],"nearestComponentName":true}],
      "assetInventory":[{"nameUnclear":true,"nearestComponentName":"A"}],
      "warnings":["Variables not renderable standalone",false],
      "components":[{"usageCount":2,"variantProperties":[]},{"usageCount":true}],
      "designTokens":{"variables":{"variables":[false]}}
    }"#).unwrap();
    let coverage = FigmaCoverage::compute(&value).unwrap();
    for (parent, field, expected) in [
        ("layoutNodes", "total", "2"),
        ("layoutNodes", "rendered", "1"),
        ("layoutNodes", "excluded", "1"),
        ("layoutNodes", "withConstraints", "1"),
        ("layoutNodes", "withRenderedPaints", "1"),
        ("assets", "total", "2"),
        ("assets", "withPath", "1"),
        ("assets", "imageFillWithPath", "0"),
        ("assets", "withNearestComponent", "1"),
        ("warnings", "other", "-1"),
        ("components", "instances", "2"),
        ("variables", "metadataAvailable", "True"),
    ] {
        assert_eq!(text(&coverage[parent][field]), expected, "{parent}.{field}");
    }
}
#[test]
fn empty_implementation_mapping_uses_layout_total() {
    let coverage = FigmaCoverage::compute(
        &PythonJson::parse(r#"{"layoutNodes":[{}],"implementationInventory":{}}"#).unwrap(),
    )
    .unwrap();
    assert_eq!(text(&coverage["layoutNodes"]["rendered"]), "1");
    assert!(FigmaCoverage::compute(&Value::Null).is_some());
}

#[test]
fn empty_report_and_problem_prefix_match_canonical_text() {
    let coverage = FigmaCoverage::compute(&Value::Null).unwrap();
    let report = crate::figma_validation_report::FigmaReport::render(&coverage, &[]).unwrap();
    assert_eq!(report, "# Figma Handoff Validation Report\n\n## ✅ No Schema Violations\n\n## Fidelity Coverage\n- Screens: 0\n- Components: 0 (instances 0 / variants 0 / blueprints 0)\n- layoutNodes: 0 (opacity 0 / stroke 0 / rotation 0 / renderBounds 0)\n- Colors 0 / gradients 0 / text styles 0 / text runs 0 / effects 0\n- Image-fill recovery: 0/0 (100%)\n- Overall asset recovery: 0/0 (0%), fallback chains 0\n- Unique icons: 0 (name unclear 0 / named by component 0), assets linked to components 0\n- Variables: 0 (metadata unavailable)\n- Warnings: 0 (asset not renderable 0 / variables 0 / other 0)\n");
    let report = crate::figma_validation_report::FigmaReport::render(
        &coverage,
        &["한글".into(), "nested\nline".into()],
    )
    .unwrap();
    assert!(report.starts_with("# Figma Handoff Validation Report\n\n## ❌ Schema Violations (2)\n- 한글\n- nested\nline\n"));
}
