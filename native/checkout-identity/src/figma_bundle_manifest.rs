//! owner: project an offline Figma summary into its ordered bundle manifest;
//! allowed imports: JSON and summary validation; forbidden imports: filesystem, network and process;
//! callers/tests: Figma manifest probe and extractor manifest fixtures;
//! verification: ordered count, default and explicit-null behavior.
use crate::python_json::{PythonJson, Value as PythonValue};
use serde_json::{json, Map, Value};

#[path = "figma_markdown_overview.rs"]
mod markdown_overview;
#[path = "figma_markdown_tokens.rs"]
mod markdown_tokens;

fn list_len(object: &Map<String, Value>, key: &str, optional: bool) -> Option<usize> {
    match object.get(key) {
        None if optional => Some(0),
        Some(Value::Array(items)) => Some(items.len()),
        _ => None,
    }
}

fn project(text: &str) -> Option<Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input: Value = serde_json::from_str(text).ok()?;
    let summary = input.get("summary")?.as_object()?;
    let args = input.get("arguments")?.as_object()?;
    // The ordinary CLI supplies a validated scale in this range. It also
    // excludes oversized integer tokens that serde_json would turn into floats.
    if !(0.01..=4.0).contains(&args.get("scale")?.as_f64()?) {
        return None;
    }
    let arguments = json!({
        "format": args.get("format")?.as_str()?,
        "scale": args.get("scale")?.as_number()?,
        "maxFlowDepth": args.get("maxFlowDepth")?.as_i64()?,
        "images": args.get("images")?.as_bool()?,
        "includeImageFills": args.get("includeImageFills")?.as_bool()?,
        "exportAssets": args.get("exportAssets")?.as_bool()?,
    });
    let empty = Map::new();
    let optional_object = |key: &str| match summary.get(key) {
        None => Some(&empty),
        Some(value) => value.as_object(),
    };
    let tokens = summary.get("designTokens")?.as_object()?;
    let variables = tokens.get("variables")?.as_object()?;
    let styles = optional_object("referencedStyles")?;
    let inventory = optional_object("implementationInventory")?;
    let mut counts = Map::new();
    for (name, owner, key, optional) in [
        ("screenCount", summary, "screens", false),
        ("flowEdgeCount", summary, "flowEdges", false),
        ("flowInteractionCount", summary, "flowInteractions", true),
        ("namedColorStyleCount", tokens, "colorStyles", false),
        ("namedTextStyleCount", tokens, "textStyles", false),
        ("namedEffectStyleCount", tokens, "effectStyles", false),
        ("variableCount", variables, "variables", true),
        ("referencedColorStyleCount", styles, "colorStyles", true),
        ("referencedTextStyleCount", styles, "textStyles", true),
        ("referencedEffectStyleCount", styles, "effectStyles", true),
        ("componentCount", summary, "components", true),
        (
            "componentBlueprintCount",
            summary,
            "componentBlueprints",
            true,
        ),
        ("colorCandidateCount", summary, "colors", false),
        ("gradientCandidateCount", summary, "gradients", true),
        ("textStyleCandidateCount", summary, "textStyles", false),
        ("textRunCount", summary, "textRuns", true),
        ("effectCandidateCount", summary, "effects", true),
        ("layoutNodeCount", summary, "layoutNodes", true),
        ("renderedNodeCount", inventory, "renderedNodeIds", true),
        ("excludedNodeCount", inventory, "excludedNodes", true),
        ("assetCandidateCount", summary, "assetCandidates", false),
        ("assetInventoryCount", summary, "assetInventory", true),
    ] {
        counts.insert(name.into(), json!(list_len(owner, key, optional)?));
    }
    let schema = summary.get("schemaVersion").cloned().unwrap_or(json!(3));
    if !matches!(&schema, Value::Null | Value::String(_) | Value::Bool(_))
        && schema.as_i64().is_none()
    {
        return None;
    }
    Some(json!({"manifest":{
        "schemaVersion":schema, "tool":"figma-handoff.py", "arguments":arguments, "summary":counts,
    }}))
}

pub(super) fn prepare(text: &str, validate_summary: bool) -> Option<Value> {
    let mut receipt = project(text)?;
    if !validate_summary {
        return Some(receipt);
    }
    let input = PythonJson::parse(text)?;
    let problems = crate::figma_validation::FigmaValidation::validate(input.get("summary")?)?;
    if let Some(warnings) = input.get("warnings") {
        let mut warnings: Vec<_> = warnings
            .as_array()?
            .iter()
            .map(|warning| warning.as_str().map(str::to_owned))
            .collect::<Option<_>>()?;
        warnings.extend(
            problems
                .iter()
                .map(|problem| format!("schema: {problem}")),
        );
        let mut summary = input.get("summary")?.as_object()?.clone();
        summary.insert(
            "warnings".into(),
            PythonValue::Array(warnings.iter().cloned().map(PythonValue::String).collect()),
        );
        let manifest = PythonJson::parse(&receipt.get("manifest")?.to_string())?;
        receipt["summary_json"] = json!(PythonJson::render(
            &PythonValue::Object(summary),
            true,
            false
        )?);
        receipt["manifest_json"] = json!(PythonJson::render(&manifest, true, false)?);
        if let Some(lines) = markdown_overview::render(input.get("summary")?) {
            receipt["markdown_overview"] = json!(lines);
        }
        for (key, lines) in markdown_tokens::render(input.get("summary")?, &warnings) {
            if let Some(lines) = lines {
                receipt[key] = json!(lines);
            }
        }
    }
    receipt
        .as_object_mut()?
        .insert("problems".into(), json!(problems));
    Some(receipt)
}
