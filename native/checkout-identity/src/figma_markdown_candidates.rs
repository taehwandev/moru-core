//! owner: Figma handoff components, blueprints and rendered candidate sections;
//! allowed imports: Python JSON and shared style formatters; forbidden imports:
//! I/O and providers; callers/tests: bundle prepare and offline candidate fixtures;
//! verification: ordered Markdown and row limits.
use crate::python_json::{Number, Object, PythonJson, Value};

fn field(row: &Value, key: &str) -> String {
    row.get(key).map(PythonJson::string).unwrap_or_default()
}
fn yes<'a>(row: &'a Value, key: &str) -> Option<&'a Value> {
    row.get(key).filter(|v| PythonJson::truthy(v))
}
fn required(row: &Value, key: &str) -> Option<String> {
    Some(PythonJson::string(row.get(key)?))
}
fn array<'a>(row: &'a Value, key: &str) -> Option<&'a [Value]> {
    match row.get(key) {
        None => Some(&[]),
        Some(v) => Some(v.as_array()?.as_slice()),
    }
}
fn join(row: &Value, key: &str, n: usize, separator: &str) -> Option<String> {
    Some(
        array(row, key)?
            .iter()
            .take(n)
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?
            .join(separator),
    )
}
fn section(lines: &mut Vec<String>, title: &str, rows: Vec<String>, empty: &str) {
    lines.extend([String::new(), format!("## {title}"), String::new()]);
    if rows.is_empty() {
        lines.push(empty.into())
    } else {
        lines.extend(rows)
    }
}
fn component(row: &Value) -> Option<String> {
    let label = yes(row, "componentSetName")
        .map(PythonJson::string)
        .unwrap_or_else(|| field(row, "name"));
    let variants = if let Some(v) = yes(row, "variantProperties") {
        let pairs = v
            .as_object()?
            .iter()
            .map(|(k, v)| format!("{k}={}", PythonJson::string(v)))
            .collect::<Vec<_>>()
            .join(", ");
        format!(" [{pairs}]")
    } else {
        String::new()
    };
    Some(format!(
        "- `{}` {label}{variants} x{} ({} screens)",
        required(row, "componentId")?,
        required(row, "usageCount")?,
        array(row, "usedInScreens")?.len()
    ))
}
fn structure(item: &Value) -> Option<String> {
    item.as_object()?;
    let depth = match item.get("depth") {
        None => 1,
        Some(Value::Number(Number::Integer(v))) => v.parse::<i64>().ok()?.max(0),
        _ => return None,
    };
    if depth > 128 {
        return None;
    }
    let mut line = format!(
        "  {}- {} ({})",
        "  ".repeat(depth as usize),
        field(item, "name"),
        field(item, "type")
    );
    if !matches!(item["w"], Value::Null) && !matches!(item["h"], Value::Null) {
        line.push_str(&format!(
            " {}x{}",
            PythonJson::string(&item["w"]),
            PythonJson::string(&item["h"])
        ))
    }
    if let Some(id) = yes(item, "componentId") {
        line.push_str(&format!(" → comp `{}`", PythonJson::string(id)))
    }
    if let Some(key) = yes(item, "assetDedupKey") {
        line.push_str(&format!(
            " [asset {}]",
            key.as_str()?.chars().take(14).collect::<String>()
        ))
    }
    if let Some(text) = yes(item, "text") {
        line.push_str(&format!(" \"{}\"", PythonJson::string(text)))
    }
    Some(line)
}
fn blueprint(row: &Value, rows: &mut Vec<String>) -> Option<()> {
    let dims = if let Some(size) = yes(row, "size") {
        size.as_object()?;
        format!(
            " {}x{}",
            PythonJson::string(&size["w"]),
            PythonJson::string(&size["h"])
        )
    } else {
        String::new()
    };
    rows.push(format!(
        "- `{}` **{}**{dims} x{}",
        required(row, "componentId")?,
        field(row, "name"),
        required(row, "usageCount")?
    ));
    for item in array(row, "structure")?.iter().take(24) {
        rows.push(structure(item)?)
    }
    Some(())
}
fn color(row: &Value) -> Option<String> {
    let var = if let Some(bound) =
        yes(row, "boundVariableNames").or_else(|| yes(row, "boundVariableIds"))
    {
        format!(" [var: {}]", bound.as_array()?.first()?.as_str()?)
    } else {
        String::new()
    };
    Some(format!(
        "- `{}` x{}{var} ({})",
        required(row, "hex")?,
        required(row, "count")?,
        join(row, "sources", 3, ", ")?
    ))
}
fn gradient(row: &Value) -> Option<String> {
    Some(format!(
        "- {} x{} ({})",
        super::gradient(row)?,
        required(row, "count")?,
        join(row, "sources", 3, ", ")?
    ))
}
fn style(row: &Value) -> Option<String> {
    let family = yes(row, "fontFamily")
        .or_else(|| yes(row, "fontPostScriptName"))
        .map(PythonJson::string)
        .unwrap_or_else(|| "unknown".into());
    let mut height = "None".to_owned();
    let mut unit = field(row, "lineHeightUnit");
    for (key, override_unit) in [
        ("lineHeightPx", None),
        ("lineHeightPercentFontSize", Some("FONT_SIZE_%")),
        ("lineHeightPercent", Some("PERCENT")),
    ] {
        if !matches!(row[key], Value::Null) {
            height = PythonJson::string(&row[key]);
            if let Some(u) = override_unit {
                unit = u.into()
            }
            break;
        }
    }
    let spacing = if matches!(row["letterSpacing"], Value::Null) {
        String::new()
    } else {
        format!(
            " letterSpacing={}({})",
            PythonJson::string(&row["letterSpacing"]),
            field(row, "letterSpacingUnit")
        )
    };
    Some(format!(
        "- `{family}` size={} weight={} lineHeight={height}({unit}){spacing} align={} x{} ({})",
        PythonJson::string(&row["fontSize"]),
        PythonJson::string(&row["fontWeight"]),
        field(row, "textAlignHorizontal"),
        required(row, "count")?,
        join(row, "samples", 2, " / ")?
    ))
}
fn text_run(row: &Value) -> Option<String> {
    let text: String = field(row, "text")
        .replace('\n', " ")
        .chars()
        .take(60)
        .collect();
    let empty = Value::Object(Object::new());
    let range = row.get("range").unwrap_or(&empty);
    range.as_object()?;
    let detail = super::text_style(row.get("resolvedStyle").unwrap_or(&empty))?;
    Some(format!(
        "- `{}` {} {}..{} `{text}`{detail}",
        required(row, "nodeId")?,
        field(row, "nodeName"),
        PythonJson::string(&range["start"]),
        PythonJson::string(&range["end"])
    ))
}
fn effect(row: &Value) -> Option<String> {
    let mut wrapper = Object::new();
    wrapper.insert("effects".into(), Value::Array(vec![row.clone()]));
    Some(format!(
        "-{} x{} ({})",
        super::effects(&Value::Object(wrapper))?,
        required(row, "count")?,
        join(row, "sources", 2, ", ")?
    ))
}
pub(super) fn render(summary: &Value) -> Option<Vec<String>> {
    let mut lines = Vec::new();
    let components = array(summary, "components")?
        .iter()
        .take(60)
        .map(component)
        .collect::<Option<_>>()?;
    section(
        &mut lines,
        "Components (usage order — rendered implementation work list)",
        components,
        "- None (no visible instances or component definitions in the payload)",
    );
    let mut blueprints = Vec::new();
    for row in array(summary, "componentBlueprints")?.iter().take(8) {
        blueprint(row, &mut blueprints)?
    }
    section(
        &mut lines,
        "Component Blueprints (internal structure — assemble from this)",
        blueprints,
        "- None",
    );
    type Row = fn(&Value) -> Option<String>;
    for (key, title, limit, render) in [
        (
            "colors",
            "Rendered Color Candidates (usage order)",
            20,
            color as Row,
        ),
        (
            "gradients",
            "Gradient Candidates (rendered nodes only)",
            20,
            gradient as Row,
        ),
        (
            "textStyles",
            "Text Style Candidates (usage order)",
            20,
            style as Row,
        ),
        ("textRuns", "Text Override Runs", 60, text_run as Row),
        ("effects", "Effect Candidates", 20, effect as Row),
    ] {
        if matches!(key, "colors" | "textStyles") {
            summary.get(key)?;
        }
        let rows = array(summary, key)?
            .iter()
            .take(limit)
            .map(render)
            .collect::<Option<_>>()?;
        section(&mut lines, title, rows, "- None");
    }
    Some(lines)
}
