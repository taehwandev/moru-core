//! owner: FigmaCoverage; allowed imports: shared PythonJson, PythonSum/std;
//! forbidden imports: I/O/schema policy; callers/tests: Figma validation/report;
//! verification: complete canonical coverage fields and Python truthiness parity.
use crate::python_json::{Number, Object, PythonJson, Value};
use std::collections::BTreeSet;
pub(crate) struct FigmaCoverage;
impl FigmaCoverage {
    pub(crate) fn compute(root: &Value) -> Option<Value> {
        let components = Self::rows(&root["components"]);
        let variables = Self::sequence(&root["designTokens"]["variables"]["variables"]);
        let length = |field: &str| Self::number(Self::sequence(&root[field]).len() as i128);
        Some(Self::object(vec![
            ("screens", length("screens")),
            (
                "components",
                Self::object(vec![
                    ("total", Self::number(components.len() as i128)),
                    (
                        "instances",
                        crate::python_sum::PythonSum::sum(
                            components.iter().map(|item| &item["usageCount"]),
                        )?,
                    ),
                    ("withVariant", Self::count(&components, "variantProperties")),
                    ("blueprints", length("componentBlueprints")),
                ]),
            ),
            ("layoutNodes", Self::layout(root)),
            ("colors", length("colors")),
            ("gradients", length("gradients")),
            ("textStyles", length("textStyles")),
            ("textRuns", length("textRuns")),
            ("effects", length("effects")),
            ("assets", Self::assets(root)),
            ("iconInventory", Self::inventory(root)),
            (
                "variables",
                Self::object(vec![
                    ("count", Self::number(variables.len() as i128)),
                    ("metadataAvailable", Value::Bool(!variables.is_empty())),
                ]),
            ),
            ("warnings", Self::warnings(root)),
        ]))
    }
    fn layout(root: &Value) -> Value {
        let layout = Self::rows(&root["layoutNodes"]);
        let implementation = &root["implementationInventory"];
        let rendered: BTreeSet<_> = Self::sequence(&implementation["renderedNodeIds"])
            .iter()
            .filter_map(Value::as_str)
            .collect();
        let count_with = |field: &str| {
            Self::number(
                layout
                    .iter()
                    .filter(|node| !matches!(node[field], Value::Null))
                    .count() as i128,
            )
        };
        Self::object(vec![
            ("total", Self::number(layout.len() as i128)),
            (
                "rendered",
                Self::number(
                    if implementation.as_object().is_some_and(|o| !o.is_empty()) {
                        rendered.len()
                    } else {
                        layout.len()
                    } as i128,
                ),
            ),
            (
                "excluded",
                Self::number(Self::rows(&implementation["excludedNodes"]).len() as i128),
            ),
            ("withRenderedPaints", Self::count(&layout, "renderedPaints")),
            ("withOpacity", count_with("opacity")),
            ("withStrokeWeight", count_with("strokeWeight")),
            ("withRotation", count_with("rotation")),
            ("withRenderBounds", count_with("absoluteRenderBounds")),
            ("withConstraints", count_with("constraints")),
        ])
    }
    fn assets(root: &Value) -> Value {
        let mut seen = BTreeSet::new();
        let assets: Vec<_> = Self::rows(&root["assetCandidates"])
            .into_iter()
            .filter(|asset| {
                asset["id"]
                    .as_str()
                    .is_some_and(|id| !id.is_empty() && seen.insert(id.to_owned()))
            })
            .collect();
        let fills: Vec<_> = assets
            .iter()
            .copied()
            .filter(|asset| PythonJson::truthy(&asset["imageRefs"]))
            .collect();
        Self::object(vec![
            ("total", Self::number(assets.len() as i128)),
            ("withPath", Self::count(&assets, "assetPath")),
            ("imageFillTotal", Self::number(fills.len() as i128)),
            ("imageFillWithPath", Self::count(&fills, "assetPath")),
            (
                "withFallbackChain",
                Self::count(&assets, "renderFallbackIds"),
            ),
            (
                "withNearestComponent",
                Self::count(&assets, "nearestComponentName"),
            ),
        ])
    }
    fn inventory(root: &Value) -> Value {
        let inventory = Self::rows(&root["assetInventory"]);
        Self::object(vec![
            ("unique", Self::number(inventory.len() as i128)),
            ("nameUnclear", Self::count(&inventory, "nameUnclear")),
            (
                "namedByComponent",
                Self::number(
                    inventory
                        .iter()
                        .filter(|item| {
                            PythonJson::truthy(&item["nameUnclear"])
                                && PythonJson::truthy(&item["nearestComponentName"])
                        })
                        .count() as i128,
                ),
            ),
        ])
    }
    fn warnings(root: &Value) -> Value {
        let warnings: Vec<_> = Self::sequence(&root["warnings"])
            .iter()
            .filter_map(Value::as_str)
            .collect();
        let assets = warnings
            .iter()
            .filter(|s| s.contains("not renderable standalone"))
            .count();
        let variables = warnings
            .iter()
            .filter(|s| s.contains("Variables") || s.contains("variables"))
            .count();
        Self::object(vec![
            ("total", Self::number(warnings.len() as i128)),
            ("assetNotRenderable", Self::number(assets as i128)),
            ("variables", Self::number(variables as i128)),
            (
                "other",
                Self::number(warnings.len() as i128 - assets as i128 - variables as i128),
            ),
        ])
    }
    fn count(rows: &[&Value], field: &str) -> Value {
        Self::number(
            rows.iter()
                .filter(|node| PythonJson::truthy(&node[field]))
                .count() as i128,
        )
    }
    fn sequence(value: &Value) -> &[Value] {
        value.as_array().map(Vec::as_slice).unwrap_or(&[])
    }
    fn rows(value: &Value) -> Vec<&Value> {
        Self::sequence(value)
            .iter()
            .filter(|item| item.is_object())
            .collect()
    }
    fn number(value: i128) -> Value {
        Value::Number(Number::Integer(value.to_string()))
    }
    fn object(fields: Vec<(&str, Value)>) -> Value {
        let mut object = Object::new();
        for (key, value) in fields {
            object.insert(key.into(), value);
        }
        Value::Object(object)
    }
}

#[cfg(test)]
#[path = "figma_coverage_tests.rs"]
mod tests;
