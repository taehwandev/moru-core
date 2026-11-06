//! owner: FigmaValidation; allowed imports: PythonJson and private validation helpers;
//! forbidden imports: IO/process/network; callers/tests: Figma summary CLI;
//! verification: ordered structural errors against figma_summary_validate.py.
#[path = "figma_validation_inventory.rs"]
mod inventory;
#[path = "figma_validation_layout.rs"]
mod layout;
use crate::python_json::{Number, PythonJson as Py, Value};
use std::collections::BTreeSet;

const REQUIRED: &[&str] = &[
    "meta",
    "screens",
    "flowEdges",
    "flowInteractions",
    "designTokens",
    "components",
    "componentBlueprints",
    "colors",
    "gradients",
    "textStyles",
    "textRuns",
    "effects",
    "layoutMetrics",
    "layoutNodes",
    "assetCandidates",
    "assetInventory",
    "warnings",
];
const LISTS: &[&str] = &[
    "screens",
    "flowEdges",
    "flowInteractions",
    "components",
    "componentBlueprints",
    "colors",
    "gradients",
    "textStyles",
    "textRuns",
    "effects",
    "layoutNodes",
    "assetCandidates",
    "assetInventory",
    "warnings",
];

pub(crate) struct FigmaValidation;
impl FigmaValidation {
    pub(crate) fn validate(summary: &Value) -> Option<Vec<String>> {
        if !summary.is_object() {
            return Some(vec!["summary is not an object".into()]);
        }
        let mut errors = Vec::new();
        let version = &summary["schemaVersion"];
        if !matches!(version, Value::Null) {
            require(
                &mut errors,
                integer_at_least(version, 1),
                format!("schemaVersion invalid: {}", Py::repr(version)),
            );
        }
        let strict = integer_at_least(version, 4);
        for key in REQUIRED {
            require(
                &mut errors,
                summary.get(key).is_some(),
                format!("missing top-level key: {key}"),
            );
        }
        if strict {
            require(
                &mut errors,
                summary.get("implementationInventory").is_some(),
                "missing top-level key: implementationInventory".into(),
            );
        }
        for key in LISTS {
            if let Some(value) = summary.get(key) {
                require(
                    &mut errors,
                    value.is_array(),
                    format!("{key} is not a list"),
                );
            }
        }
        for key in [
            "meta",
            "designTokens",
            "layoutMetrics",
            "implementationInventory",
        ] {
            if let Some(value) = summary.get(key) {
                require(
                    &mut errors,
                    value.is_object(),
                    format!("{key} is not an object"),
                );
            }
        }
        for key in ["fileKey", "startNodeId", "generatedAt"] {
            require(
                &mut errors,
                Py::truthy(&summary["meta"][key]),
                format!("meta.{key} missing"),
            );
        }
        for (i, screen) in sequence(&summary["screens"]).iter().enumerate() {
            if !screen.is_object() {
                errors.push(format!("screens[{i}] is not an object"));
                continue;
            }
            require(
                &mut errors,
                Py::truthy(&screen["id"]),
                format!("screens[{i}].id missing"),
            );
        }
        for (i, color) in sequence(&summary["colors"]).iter().enumerate() {
            if !color.is_object() {
                errors.push(format!("colors[{i}] is not an object"));
                continue;
            }
            require(
                &mut errors,
                hex(&color["hex"]),
                format!("colors[{i}].hex invalid: {}", Py::repr(&color["hex"])),
            );
        }
        Self::gradients(&mut errors, summary);
        let ids = layout::validate(&mut errors, &summary["layoutNodes"], strict);
        for (collection, id, count) in [
            ("assetCandidates", "id", None),
            ("components", "componentId", Some("usageCount")),
            ("assetInventory", "dedupKey", Some("usageCount")),
        ] {
            Self::identified(&mut errors, summary, collection, id, count);
        }
        let excluded = inventory::validate(
            &mut errors,
            &summary["implementationInventory"],
            strict,
            &ids,
        );
        Self::leaks(&mut errors, summary, &excluded)?;
        inventory::components(&mut errors, summary, strict, &excluded);
        require(
            &mut errors,
            summary["designTokens"].get("variables").is_some(),
            "designTokens.variables missing".into(),
        );
        Some(errors)
    }

    fn gradients(errors: &mut Vec<String>, summary: &Value) {
        for (i, gradient) in sequence(&summary["gradients"]).iter().enumerate() {
            if !gradient.is_object() {
                errors.push(format!("gradients[{i}] is not an object"));
                continue;
            }
            let empty = Value::Array(Vec::new());
            let stops = gradient.get("stops").unwrap_or(&empty);
            if !stops.is_array() {
                errors.push(format!("gradients[{i}].stops is not a list"));
                continue;
            }
            for (j, stop) in sequence(stops).iter().enumerate() {
                if !stop.is_object() {
                    errors.push(format!("gradients[{i}].stops[{j}] is not an object"));
                    continue;
                }
                let position = &stop["position"];
                if !matches!(position, Value::Null) {
                    require(
                        errors,
                        unit(position),
                        format!(
                            "gradients[{i}].stops[{j}].position out of [0,1]: {}",
                            Py::repr(position)
                        ),
                    );
                }
            }
        }
    }

    fn identified(
        errors: &mut Vec<String>,
        summary: &Value,
        collection: &str,
        id: &str,
        count: Option<&str>,
    ) {
        for (i, item) in sequence(&summary[collection]).iter().enumerate() {
            if !item.is_object() {
                errors.push(format!("{collection}[{i}] is not an object"));
                continue;
            }
            require(
                errors,
                Py::truthy(&item[id]),
                format!("{collection}[{i}].{id} missing"),
            );
            if let Some(count) = count {
                require(
                    errors,
                    numeric(&item[count]).is_some_and(|n| n >= 1.0),
                    format!(
                        "{collection}[{i}].{count} invalid: {}",
                        Py::repr(&item[count])
                    ),
                );
            }
        }
    }

    fn leaks(errors: &mut Vec<String>, summary: &Value, excluded: &BTreeSet<String>) -> Option<()> {
        for (collection, field) in [
            ("assetCandidates", "id"),
            ("flowEdges", "fromNodeId"),
            ("flowInteractions", "fromNodeId"),
        ] {
            for item in sequence(&summary[collection]) {
                if !item.is_object() {
                    continue;
                }
                let id = &item[field];
                if matches!(id, Value::Array(_) | Value::Object(_)) {
                    return None;
                }
                if id.as_str().is_some_and(|id| excluded.contains(id)) {
                    let kind = if collection == "assetCandidates" {
                        "node"
                    } else {
                        "source node"
                    };
                    errors.push(format!(
                        "{collection} includes excluded {kind} id: {}",
                        Py::string(id)
                    ));
                }
            }
        }
        Some(())
    }
}

fn sequence(value: &Value) -> &[Value] {
    value.as_array().map(Vec::as_slice).unwrap_or(&[])
}
fn require(errors: &mut Vec<String>, condition: bool, message: String) {
    if !condition {
        errors.push(message);
    }
}
fn ids(value: &Value) -> bool {
    value.as_array().is_some_and(|items| {
        items
            .iter()
            .all(|item| item.as_str().is_some_and(|s| !s.is_empty()))
    })
}
fn reasons(value: &Value) -> bool {
    ids(value) && Py::truthy(value)
}
fn numeric(value: &Value) -> Option<f64> {
    match value {
        Value::Number(Number::Float(n)) => Some(*n),
        Value::Number(Number::Integer(s)) => s.parse::<f64>().ok(),
        _ => None,
    }
}
fn unit(value: &Value) -> bool {
    numeric(value).is_some_and(|n| (-0.001..=1.001).contains(&n))
}
fn integer_at_least(value: &Value, minimum: u64) -> bool {
    let Value::Number(Number::Integer(value)) = value else {
        return false;
    };
    let minimum = minimum.to_string();
    !value.starts_with('-')
        && (value.len() > minimum.len() || (value.len() == minimum.len() && value >= &minimum))
}
fn hex(value: &Value) -> bool {
    value.as_str().is_some_and(|value| {
        let value = value.strip_suffix('\n').unwrap_or(value);
        matches!(value.len(), 7 | 9)
            && value.starts_with('#')
            && value.as_bytes()[1..]
                .iter()
                .all(|c| c.is_ascii_digit() || (b'A'..=b'F').contains(c))
    })
}

#[cfg(test)]
#[path = "figma_validation_tests.rs"]
mod tests;
