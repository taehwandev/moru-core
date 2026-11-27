//! owner: Figma dry-run output projection; allowed imports: target resolution,
//! ordered Python JSON and text helpers; forbidden imports: I/O and providers;
//! callers/tests: guarded Figma plan probe and offline CLI fixtures;
//! verification: exact UTF-8 output and fallback parity.
use crate::{
    python_json::{Object, PythonJson, Value},
    text::Text,
};
use serde_json::json;

fn slug(value: &str) -> String {
    let mut result = String::new();
    let mut replacing = false;
    for c in value.chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
            result.push(c.to_ascii_lowercase());
            replacing = false;
        } else if !replacing {
            result.push('-');
            replacing = true;
        }
    }
    let trimmed = result.trim_matches(['.', '_', '-']);
    if trimmed.is_empty() {
        "figma-handoff".into()
    } else {
        trimmed.to_owned()
    }
}

pub(super) fn render(text: &str) -> Option<serde_json::Value> {
    let target = super::target::Target::resolve(text)?;
    if target.get("error").is_some() {
        return Some(target);
    }
    let input = PythonJson::parse(text)?;
    let file = target["file_key"].as_str()?;
    let node = target["node_id"].as_str()?;
    let name = match input.get("name")? {
        Value::Null => "",
        value => Text::py_strip(value.as_str()?),
    };
    let name = if name.is_empty() {
        slug(&format!("node-{}", node.replace(':', "-")))
    } else {
        slug(name)
    };
    let base = input.get("output_base")?.as_str()?;
    let directory = match base {
        "." => name,
        "/" | "//" => format!("{base}{name}"),
        "" => return None,
        _ if base.ends_with('/') => return None,
        _ => format!("{base}/{name}"),
    };
    let mut plan = Object::new();
    for (key, value) in [
        ("fileKey", file),
        ("startNodeId", node),
        ("outputDir", &directory),
    ] {
        plan.insert(key.into(), Value::String(value.into()));
    }
    for (key, field) in [
        ("images", "images"),
        ("format", "format"),
        ("scale", "scale"),
        ("maxFlowDepth", "max_flow_depth"),
        ("timeout", "timeout"),
        ("exportAssets", "export_assets"),
        ("maxAssets", "max_assets"),
    ] {
        plan.insert(key.into(), input.get(field)?.clone());
    }
    let mut output = PythonJson::render(&Value::Object(plan), true, false)?;
    output.push('\n');
    Some(json!({"stdout":output}))
}
