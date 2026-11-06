//! owner: inventory validation; allowed imports: parent pure JSON helpers;
//! forbidden imports: IO/process/network; callers/tests: FigmaValidation;
//! verification: partition, exclusions, components and text error ordering.
use super::*;
pub(super) fn validate(
    errors: &mut Vec<String>,
    inventory: &Value,
    strict: bool,
    layout: &layout::LayoutIds,
) -> BTreeSet<String> {
    let mut excluded = BTreeSet::new();
    if !inventory.is_object() || !Py::truthy(inventory) {
        return excluded;
    }
    let rendered = &inventory["renderedNodeIds"];
    let values = &inventory["excludedNodes"];
    require(
        errors,
        ids(rendered),
        "implementationInventory.renderedNodeIds is not a list of ids".into(),
    );
    require(
        errors,
        values.is_array(),
        "implementationInventory.excludedNodes is not a list".into(),
    );
    let rendered: BTreeSet<String> = sequence(rendered)
        .iter()
        .filter_map(Value::as_str)
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .collect();
    for (i, node) in sequence(values).iter().enumerate() {
        if !node.is_object() {
            errors.push(format!(
                "implementationInventory.excludedNodes[{i}] is not an object"
            ));
            continue;
        }
        let id = node["id"].as_str().filter(|s| !s.is_empty());
        require(
            errors,
            id.is_some(),
            format!("implementationInventory.excludedNodes[{i}].id missing"),
        );
        require(
            errors,
            reasons(&node["reasons"]),
            format!("implementationInventory.excludedNodes[{i}].reasons missing"),
        );
        if let Some(id) = id {
            excluded.insert(id.into());
        }
    }
    let overlap: Vec<_> = rendered.intersection(&excluded).cloned().collect();
    if !overlap.is_empty() {
        errors.push(format!(
            "implementationInventory rendered and excluded node ids overlap: {}",
            overlap.join(", ")
        ));
    }
    if strict {
        let union: BTreeSet<_> = rendered.union(&excluded).cloned().collect();
        require(
            errors,
            union == layout.all,
            "implementationInventory does not partition all layout node ids".into(),
        );
        require(
            errors,
            rendered == layout.rendered,
            "implementationInventory.renderedNodeIds disagrees with effectiveVisible".into(),
        );
        require(
            errors,
            excluded == layout.excluded,
            "implementationInventory.excludedNodes disagrees with effectiveVisible".into(),
        );
    }
    excluded
}

pub(super) fn components(
    errors: &mut Vec<String>,
    summary: &Value,
    strict: bool,
    excluded: &BTreeSet<String>,
) {
    for (i, component) in sequence(&summary["components"]).iter().enumerate() {
        if !component.is_object() {
            continue;
        }
        let instances = &component["instanceNodeIds"];
        if strict {
            require(
                errors,
                ids(instances),
                format!("components[{i}].instanceNodeIds is not a list of ids"),
            );
        }
        let leaked: BTreeSet<_> = sequence(instances)
            .iter()
            .filter_map(Value::as_str)
            .filter(|id| excluded.contains(*id))
            .collect();
        if !leaked.is_empty() {
            errors.push(format!(
                "components[{i}].instanceNodeIds includes excluded node ids: {}",
                leaked.into_iter().collect::<Vec<_>>().join(", ")
            ));
        }
    }
    for (i, blueprint) in sequence(&summary["componentBlueprints"]).iter().enumerate() {
        if !blueprint.is_object() {
            errors.push(format!("componentBlueprints[{i}] is not an object"));
            continue;
        }
        require(
            errors,
            Py::truthy(&blueprint["componentId"]),
            format!("componentBlueprints[{i}].componentId missing"),
        );
        require(
            errors,
            blueprint["structure"].is_array(),
            format!("componentBlueprints[{i}].structure not a list"),
        );
    }
    for (i, style) in sequence(&summary["textStyles"]).iter().enumerate() {
        if !style.is_object() {
            errors.push(format!("textStyles[{i}] is not an object"));
            continue;
        }
        let size = &style["fontSize"];
        if !matches!(size, Value::Null) {
            require(
                errors,
                numeric(size).is_some_and(|n| n > 0.0),
                format!("textStyles[{i}].fontSize invalid: {}", Py::repr(size)),
            );
        }
    }
}
