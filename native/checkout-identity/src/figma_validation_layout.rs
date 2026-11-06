//! owner: layout validation; allowed imports: parent pure JSON helpers;
//! forbidden imports: IO/process/network; callers/tests: FigmaValidation;
//! verification: visibility, paint ordering and geometry structural errors.
use super::*;
pub(super) struct LayoutIds {
    pub(super) all: BTreeSet<String>,
    pub(super) rendered: BTreeSet<String>,
    pub(super) excluded: BTreeSet<String>,
}
pub(super) fn validate(errors: &mut Vec<String>, nodes: &Value, strict: bool) -> LayoutIds {
    let mut result = LayoutIds {
        all: BTreeSet::new(),
        rendered: BTreeSet::new(),
        excluded: BTreeSet::new(),
    };
    for (i, node) in sequence(nodes).iter().enumerate() {
        if !node.is_object() {
            errors.push(format!("layoutNodes[{i}] is not an object"));
            continue;
        }
        require(
            errors,
            Py::truthy(&node["id"]),
            format!("layoutNodes[{i}].id missing"),
        );
        let id = node.get("id").map(Py::string).unwrap_or_default();
        if !id.is_empty() {
            result.all.insert(id.clone());
        }
        require(
            errors,
            node.get("type").is_some(),
            format!("layoutNodes[{i}].type missing"),
        );
        let visible = &node["visible"];
        if !matches!(visible, Value::Null) {
            require(
                errors,
                matches!(visible, Value::Bool(_)),
                format!(
                    "layoutNodes[{i}].visible not a boolean: {}",
                    Py::repr(visible)
                ),
            );
        }
        let opacity = &node["opacity"];
        if !matches!(opacity, Value::Null) {
            require(
                errors,
                unit(opacity),
                format!(
                    "layoutNodes[{i}].opacity out of [0,1]: {}",
                    Py::repr(opacity)
                ),
            );
        }
        let effective = &node["effectiveVisible"];
        if strict {
            require(
                errors,
                matches!(effective, Value::Bool(_)),
                format!(
                    "layoutNodes[{i}].effectiveVisible not a boolean: {}",
                    Py::repr(effective)
                ),
            );
        }
        let reason = &node["visibilityReasons"];
        match effective {
            Value::Bool(false) => {
                result.excluded.insert(id);
                require(
                    errors,
                    reasons(reason),
                    format!("layoutNodes[{i}].visibilityReasons missing for excluded node"),
                );
            }
            Value::Bool(true) => {
                result.rendered.insert(id);
                require(
                    errors,
                    matches!(reason, Value::Null) || reason.as_array().is_some_and(Vec::is_empty),
                    format!("layoutNodes[{i}].visibilityReasons present for rendered node"),
                );
            }
            _ => {}
        }
        paints(errors, node, i);
        let stroke = &node["strokeWeight"];
        if !matches!(stroke, Value::Null) {
            require(
                errors,
                numeric(stroke).is_some_and(|n| n >= 0.0),
                format!(
                    "layoutNodes[{i}].strokeWeight invalid: {}",
                    Py::repr(stroke)
                ),
            );
        }
        let bounds = &node["absoluteBoundingBox"];
        if !matches!(bounds, Value::Null) {
            require(
                errors,
                bounds.is_object()
                    && ["x", "y", "width", "height"]
                        .iter()
                        .all(|key| matches!(&bounds[*key], Value::Number(_))),
                format!("layoutNodes[{i}].absoluteBoundingBox malformed"),
            );
        }
    }
    result
}

fn paints(errors: &mut Vec<String>, node: &Value, i: usize) {
    let stack = &node["renderedPaints"];
    if matches!(stack, Value::Null) {
        return;
    }
    let Some(stack) = stack.as_object() else {
        errors.push(format!("layoutNodes[{i}].renderedPaints is not an object"));
        return;
    };
    for (field, paints) in stack.iter() {
        if !paints.is_array() {
            errors.push(format!(
                "layoutNodes[{i}].renderedPaints.{field} is not a list"
            ));
            continue;
        }
        for (j, paint) in sequence(paints).iter().enumerate() {
            let prefix = format!("layoutNodes[{i}].renderedPaints.{field}[{j}]");
            if !paint.is_object() {
                errors.push(format!("{prefix} is not an object"));
                continue;
            }
            require(
                errors,
                Py::truthy(&paint["type"]),
                format!("{prefix}.type missing"),
            );
            let color = &paint["hex"];
            if !matches!(color, Value::Null) {
                require(
                    errors,
                    hex(color),
                    format!("{prefix}.hex invalid: {}", Py::repr(color)),
                );
            }
        }
    }
}
