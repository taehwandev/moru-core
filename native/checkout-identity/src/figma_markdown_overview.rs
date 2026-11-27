//! owner: Figma Markdown source, screen, visibility and prototype sections;
//! allowed imports: pure Python JSON formatting; forbidden imports: I/O and network;
//! callers/tests: guarded bundle preparation and Markdown overview fixtures;
//! verification: line-for-line offline rendering.
use crate::python_json::{PythonJson, Value};

fn field(row: &Value, key: &str) -> String {
    row.get(key).map(PythonJson::string).unwrap_or_default()
}
fn truth<'a>(row: &'a Value, key: &str) -> Option<&'a Value> {
    row.get(key).filter(|v| PythonJson::truthy(v))
}
fn list<'a>(row: &'a Value, key: &str) -> Option<&'a [Value]> {
    match row.get(key) {
        None => Some(&[]),
        Some(v) => Some(v.as_array()?.as_slice()),
    }
}
fn section(lines: &mut Vec<String>, title: &str, rows: Vec<String>, empty: &str) {
    lines.extend([String::new(), format!("## {title}"), String::new()]);
    if rows.is_empty() {
        lines.push(empty.into())
    } else {
        lines.extend(rows)
    }
}
fn screen(row: &Value) -> Option<String> {
    let size = match (&row["width"], &row["height"]) {
        (Value::Null, _) | (_, Value::Null) => String::new(),
        (w, h) => format!(" / {}x{}", PythonJson::string(w), PythonJson::string(h)),
    };
    let image = truth(row, "imagePath")
        .map(|v| format!(" / image: `{}`", PythonJson::string(v)))
        .unwrap_or_default();
    Some(format!(
        "- `{}` {} ({}{size}){image}",
        PythonJson::string(row.get("id")?),
        field(row, "name"),
        field(row, "type")
    ))
}
fn visibility(lines: &mut Vec<String>, summary: &Value) -> Option<()> {
    let inventory = &summary["implementationInventory"];
    if !inventory.is_object() {
        section(lines,"Implementation Visibility Gate",Vec::new(),"- Legacy summary without an implementation inventory. Resolve node and ancestor visibility from `layoutNodes` and the rendered frame before implementation.");
        return Some(());
    }
    let excluded = list(inventory, "excludedNodes")?;
    section(lines,"Implementation Visibility Gate",vec![
        format!("- Implement only the {} nodes in `implementationInventory.renderedNodeIds`.",list(inventory,"renderedNodeIds")?.len()),
        format!("- Do not implement the {} nodes listed under `excludedNodes`, including their controls, callbacks, actions, assets, or styles.",excluded.len()),
        "- A listed component or raw layout node is not implementation evidence unless it is effectively visible in the rendered state.".into(),
    ],"- None");
    let mut rows = Vec::new();
    for node in excluded {
        node.as_object()?;
        let reasons = list(node, "reasons")?
            .iter()
            .map(PythonJson::string)
            .collect::<Vec<_>>()
            .join(", ");
        rows.push(format!(
            "- `{}` {} ({}) — {}",
            field(node, "id"),
            field(node, "name"),
            field(node, "type"),
            if reasons.is_empty() {
                "reason unavailable"
            } else {
                &reasons
            }
        ));
    }
    section(lines, "Do Not Implement — Excluded Nodes", rows, "- None");
    Some(())
}
fn edge(row: &Value) -> Option<String> {
    let name = match truth(row, "toName") {
        None => String::new(),
        Some(v) => format!(" {}", v.as_str()?),
    };
    Some(format!(
        "- `{}` {} -> `{}`{name}",
        PythonJson::string(row.get("fromNodeId")?),
        field(row, "fromName"),
        PythonJson::string(row.get("toNodeId")?)
    ))
}
fn interaction(row: &Value) -> Option<String> {
    let word = |key, default: &str| {
        truth(row, key)
            .map(PythonJson::string)
            .unwrap_or_else(|| default.into())
    };
    let mut line = format!(
        "- `{}` {} {} {}",
        PythonJson::string(row.get("fromNodeId")?),
        field(row, "fromName"),
        word("triggerType", "trigger?"),
        word("actionType", "action?")
    );
    if let Some(v) = truth(row, "navigation") {
        line.push_str(&format!("/{}", PythonJson::string(v)))
    }
    if let Some(v) = truth(row, "toNodeId") {
        line.push_str(&format!(" -> `{}`", PythonJson::string(v)));
        if let Some(name) = truth(row, "toName") {
            line.push_str(&format!(" {}", PythonJson::string(name)))
        }
    }
    let transition = &row["transition"];
    let mut bits: Vec<_> = ["type", "easingType"]
        .into_iter()
        .filter_map(|k| truth(transition, k))
        .map(PythonJson::string)
        .collect();
    if let Some(v) = transition
        .get("durationSeconds")
        .filter(|v| !matches!(v, Value::Null))
    {
        bits.insert(bits.len().min(1), format!("{}s", PythonJson::string(v)));
    }
    if !bits.is_empty() {
        line.push_str(&format!(" ({})", bits.join(", ")))
    }
    if row["destinationSource"].as_str() == Some("transitionNodeID") {
        line.push_str(" [transitionNodeID]")
    }
    Some(line)
}

pub(super) fn render(summary: &Value) -> Option<Vec<String>> {
    let meta = summary.get("meta")?;
    let mut lines=vec!["# Figma Handoff".into(),"".into(),"This file is a shared implementation reference generated from the Figma REST API. It is not an automatic conversion; it gives iOS and Android implementers a common view of the screen structure and token candidates.".into(),"".into(),"## Source".into(),"".into()];
    for key in ["fileKey", "startNodeId", "generatedAt"] {
        lines.push(format!("- {key}: `{}`", PythonJson::string(meta.get(key)?)))
    }
    if let Some(url) = truth(meta, "sourceUrl") {
        lines.push(format!("- sourceUrl: {}", PythonJson::string(url)))
    }
    section(
        &mut lines,
        "Screens",
        summary
            .get("screens")?
            .as_array()?
            .iter()
            .map(screen)
            .collect::<Option<_>>()?,
        "- None",
    );
    visibility(&mut lines, summary)?;
    section(&mut lines,"Prototype Flow Edges",summary.get("flowEdges")?.as_array()?.iter().map(edge).collect::<Option<_>>()?,"- No prototype transition was found in the Figma JSON. The prototype may have no connection or the API payload may not include it.");
    let interactions = list(summary, "flowInteractions")?;
    let mut rows = interactions
        .iter()
        .take(120)
        .map(interaction)
        .collect::<Option<Vec<_>>>()?;
    if interactions.len() > 120 {
        rows.push(format!("- ... and {} more", interactions.len() - 120));
    }
    section(&mut lines, "Prototype Interaction Details", rows, "- None");
    Some(lines)
}
