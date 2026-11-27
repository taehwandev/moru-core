//! Owner: rendered layout, metric and asset rows, checklists and final warnings.
//! Allowed imports: Python JSON and shared Markdown helpers. Forbidden: I/O and network.
//! Callers/tests: bundle preparation and offline Markdown parity.
use super::{arr, field, gradient, section, yes};
use crate::python_json::{PythonJson, Value};

fn rendered_paints(node: &Value) -> Option<Vec<String>> {
    let mut fields = Vec::new();
    let Some(stack) = node.get("renderedPaints") else {
        return Some(fields);
    };
    for (name, paints) in stack.as_object()?.iter() {
        let Some(paints) = paints.as_array() else {
            continue;
        };
        let mut values = Vec::new();
        for paint in paints.iter().filter(|paint| paint.is_object()) {
            let value = if let Some(hex) = yes(paint, "hex") {
                PythonJson::string(hex)
            } else if paint["gradient"].is_object() {
                gradient(&paint["gradient"])?
            } else {
                field(paint, "type")
            };
            values.push(value);
        }
        if !values.is_empty() {
            fields.push(format!("{name}=[{}]", values.join("; ")));
        }
    }
    Some(fields)
}

fn layout_node(node: &Value) -> Option<String> {
    let mut row = format!(
        "- `{}` {} ({})",
        PythonJson::string(node.get("id")?),
        field(node, "name"),
        field(node, "type")
    );
    if let Some(parent) = yes(node, "parentId") {
        row.push_str(&format!(" parent=`{}`", PythonJson::string(parent)));
    }
    for name in [
        "layoutMode",
        "layoutWrap",
        "layoutPositioning",
        "layoutAlign",
        "layoutGrow",
        "primaryAxisSizingMode",
        "counterAxisSizingMode",
        "itemSpacing",
        "opacity",
        "rotation",
        "strokeWeight",
        "strokeAlign",
    ] {
        if let Some(value) = node.get(name).filter(|v| !matches!(v, Value::Null)) {
            row.push_str(&format!(" {name}={}", PythonJson::string(value)));
        }
    }
    for paint in rendered_paints(node)? {
        row.push(' ');
        row.push_str(&paint);
    }
    Some(row)
}

fn layout(lines: &mut Vec<String>, summary: &Value) -> Option<()> {
    let mut metrics = Vec::new();
    for (key, items) in summary.get("layoutMetrics")?.as_object()?.iter() {
        let values = items
            .as_array()?
            .iter()
            .take(10)
            .map(|item| {
                Some(format!(
                    "{}({})",
                    PythonJson::string(item.get("value")?),
                    PythonJson::string(item.get("count")?)
                ))
            })
            .collect::<Option<Vec<_>>>()?;
        metrics.push(format!("- {key}: {}", values.join(", ")));
    }
    section(lines, "Layout Metric Candidates", metrics);
    let mut rows = Vec::new();
    for node in arr(summary, "layoutNodes")? {
        // Python checks visibility on all nodes before slicing the first 120.
        node.as_object()?;
        if !matches!(&node["effectiveVisible"], Value::Bool(false)) && rows.len() < 120 {
            rows.push(layout_node(node)?);
        }
    }
    section(
        lines,
        "Rendered Layout Nodes (implementation allowlist)",
        rows,
    );
    Some(())
}

fn assets(lines: &mut Vec<String>, summary: &Value) -> Option<()> {
    let mut inventory = Vec::new();
    for item in arr(summary, "assetInventory")?.iter().take(60) {
        let mut row = format!("- {}", field(item, "name"));
        if let Some(component) = yes(item, "nearestComponentName") {
            row.push_str(&format!(" (component: {})", component.as_str()?));
        }
        row.push_str(&format!(
            " ({}) x{}",
            field(item, "type"),
            PythonJson::string(item.get("usageCount")?)
        ));
        if yes(item, "nameUnclear").is_some() {
            row.push_str(" ⚠️name unclear");
        }
        inventory.push(row);
    }
    section(
        lines,
        "Unique Icon Inventory (deduplication — avoid duplicate implementations)",
        inventory,
    );
    let mut candidates = Vec::new();
    for asset in summary.get("assetCandidates")?.as_array()?.iter().take(50) {
        let mut row = format!(
            "- `{}` {} ({})",
            PythonJson::string(asset.get("id")?),
            field(asset, "name"),
            field(asset, "type")
        );
        if let Some(component) = yes(asset, "nearestComponentName") {
            row.push_str(&format!(" [component: {}]", component.as_str()?));
        }
        candidates.push(row);
    }
    section(lines, "Rendered Asset Candidates", candidates);
    Some(())
}

pub(super) fn render(summary: &Value, warnings: &[String]) -> Option<Vec<String>> {
    let mut lines = Vec::new();
    layout(&mut lines, summary)?;
    assets(&mut lines, summary)?;
    lines.extend(CHECKLIST.iter().map(|text| (*text).to_owned()));
    if !warnings.is_empty() {
        section(
            &mut lines,
            "Warnings",
            warnings
                .iter()
                .map(|warning| format!("- {warning}"))
                .collect(),
        );
    }
    Some(lines)
}

const CHECKLIST: &[&str] = &[
    "",
    "## Platform-neutral Implementation Checklist",
    "",
    "- Read the target repository's instructions, screen entry points, navigation, and state ownership first.",
    "- Start from `implementationInventory.renderedNodeIds`; never implement a node in `excludedNodes`.",
    "- Map each visible node's exact `renderedPaints` to the target product's tokens. A nearby token is valid only when it reproduces the same paint stack.",
    "- Implement reusable components from `componentBlueprints` and `components` first.",
    "- Use the full-frame image only as a comparison reference; implement the actual structure and individual assets.",
    "- Before completion, compare visible controls and emitted actions in both directions and require zero unmatched implementation items.",
    "- Follow the target repository's current accessibility, responsive behavior, tests, and preview rules.",
    "",
    "## Missing State Log",
    "",
    "- Add states that Figma does not specify to this section during implementation.",
];
