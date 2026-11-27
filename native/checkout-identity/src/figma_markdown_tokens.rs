//! owner: Figma handoff named and referenced design-token Markdown sections;
//! allowed imports: Python JSON; forbidden imports: I/O and provider APIs;
//! callers/tests: bundle preparation and offline token rendering fixtures;
//! verification: ordered token rows and reference parity.
use crate::python_json::{PythonJson, Value};

fn s(v: &Value) -> String {
    PythonJson::string(v)
}
fn field(v: &Value, k: &str) -> String {
    v.get(k).map(s).unwrap_or_default()
}
fn yes<'a>(v: &'a Value, k: &str) -> Option<&'a Value> {
    v.get(k).filter(|x| PythonJson::truthy(x))
}
fn arr<'a>(v: &'a Value, k: &str) -> Option<&'a [Value]> {
    match v.get(k) {
        None => Some(&[]),
        Some(x) => Some(x.as_array()?.as_slice()),
    }
}
fn obj<'a>(v: &'a Value, k: &str) -> Option<&'a Value> {
    let x = &v[k];
    (v.get(k).is_none() || x.is_object()).then_some(x)
}
fn section(lines: &mut Vec<String>, title: &str, rows: Vec<String>) {
    lines.extend([String::new(), format!("## {title}"), String::new()]);
    if rows.is_empty() {
        lines.push("- None".into())
    } else {
        lines.extend(rows)
    }
}
fn gradient(v: &Value) -> Option<String> {
    v.as_object()?;
    let stops = arr(v, "stops")?
        .iter()
        .map(|x| {
            x.as_object()?;
            Some(format!(
                "{}@{}",
                yes(x, "hex").map(s).unwrap_or_else(|| "?".into()),
                s(&x["position"])
            ))
        })
        .collect::<Option<Vec<_>>>()?
        .join(" -> ");
    let handles = arr(v, "handlePositions")?
        .iter()
        .map(|x| {
            x.as_object()?;
            Some(format!("{},{}", s(&x["x"]), s(&x["y"])))
        })
        .collect::<Option<Vec<_>>>()?
        .join(" -> ");
    let kind = field(v, "type");
    if stops.is_empty() {
        return Some(kind);
    }
    let mut details = String::new();
    if !matches!(&v["angleDegrees"], Value::Null) {
        details = format!(" angle={}deg", s(&v["angleDegrees"]))
    }
    if !handles.is_empty() {
        details.push_str(&format!(" handles={handles}"))
    }
    Some(format!("{kind}({stops}{details})"))
}
fn colors(v: &Value, remote: bool) -> Option<String> {
    let mut values: Vec<_> = arr(v, "hexValues")?
        .iter()
        .map(|x| format!("`{}`", s(x)))
        .collect();
    for g in arr(v, "gradientValues")? {
        values.push(gradient(g)?)
    }
    if remote && values.is_empty() {
        if let Some(x) = yes(v, "hex") {
            values.push(format!("`{}`", s(x)))
        }
    }
    if remote && values.is_empty() {
        if let Some(x) = yes(v, "gradient") {
            values.push(gradient(x)?)
        }
    }
    Some(if values.is_empty() {
        " (color details unavailable)".into()
    } else {
        format!(" {}", values.join(" "))
    })
}
fn text_style(v: &Value) -> Option<String> {
    v.as_object()?;
    let Some(family) = yes(v, "fontFamily").or_else(|| yes(v, "fontPostScriptName")) else {
        return Some(" (font information unavailable)".into());
    };
    let (height, unit) = if !matches!(&v["lineHeightPx"], Value::Null) {
        (&v["lineHeightPx"], field(v, "lineHeightUnit"))
    } else if !matches!(&v["lineHeightPercentFontSize"], Value::Null) {
        (&v["lineHeightPercentFontSize"], "FONT_SIZE_%".into())
    } else if !matches!(&v["lineHeightPercent"], Value::Null) {
        (&v["lineHeightPercent"], "PERCENT".into())
    } else {
        (&Value::Null, field(v, "lineHeightUnit"))
    };
    let spacing = if matches!(&v["letterSpacing"], Value::Null) {
        String::new()
    } else {
        format!(
            " ls={}({})",
            s(&v["letterSpacing"]),
            field(v, "letterSpacingUnit")
        )
    };
    Some(format!(
        " {} {} {}px lh={}({unit}){spacing}",
        s(family),
        s(&v["fontWeight"]),
        s(&v["fontSize"]),
        s(height)
    ))
}
fn effects(v: &Value) -> Option<String> {
    let mut values = Vec::new();
    for e in arr(v, "effects")? {
        e.as_object()?;
        let kind = field(e, "type");
        let radius = s(&e["radius"]);
        let details = if matches!(kind.as_str(), "DROP_SHADOW" | "INNER_SHADOW") {
            format!(
                "{} offset={},{} r={radius}",
                yes(e, "color").map(s).unwrap_or_else(|| "?".into()),
                s(&e["offsetX"]),
                s(&e["offsetY"])
            )
        } else {
            format!("r={radius}")
        };
        values.push(format!("{kind}({details})"));
    }
    Some(if values.is_empty() {
        " (no details)".into()
    } else {
        format!(" {}", values.join(" "))
    })
}
fn rows(data: &Value, key: &str, remote: bool) -> Option<Vec<String>> {
    let mut rows = Vec::new();
    for style in arr(data, key)? {
        let details = match key {
            "colorStyles" => colors(style, remote)?,
            "textStyles" => text_style(style)?,
            _ => effects(style)?,
        };
        let suffix = if remote {
            if yes(style, "remote").is_some() {
                " [remote]".into()
            } else {
                String::new()
            }
        } else if key != "colorStyles" {
            match yes(style, "description") {
                Some(x) => format!(" — {}", x.as_str()?),
                None => String::new(),
            }
        } else {
            yes(style, "description")
                .map(|x| format!(" — {}", s(x)))
                .unwrap_or_default()
        };
        rows.push(format!("- `{}`{details}{suffix}", s(style.get("name")?)));
    }
    Some(rows)
}
fn variable_value(v: &Value) -> String {
    if let Some(x) = yes(v, "hex") {
        return s(x);
    }
    if let Some(x) = yes(v, "alias") {
        let resolved = yes(v, "resolvedHex")
            .map(|x| format!(" = {}", s(x)))
            .unwrap_or_default();
        return format!("-> {}{resolved}", s(yes(v, "aliasName").unwrap_or(x)));
    }
    s(v)
}
fn variables(data: &Value) -> Option<Vec<String>> {
    let mut collections = std::collections::HashMap::new();
    for c in arr(data, "collections")? {
        c.as_object()?;
        let id = match c.get("id") {
            None => "",
            Some(x) => x.as_str()?,
        };
        collections.insert(id, field(c, "name"));
    }
    let vars = arr(data, "variables")?;
    let mut rows = Vec::new();
    for v in vars.iter().take(60) {
        let id = match v.get("collectionId") {
            None => "",
            Some(x) => x.as_str()?,
        };
        let value = match yes(v, "valuesByMode") {
            None => String::new(),
            Some(x) => variable_value(x.as_object()?.iter().next()?.1),
        };
        rows.push(format!(
            "- `{}/{}` ({}) = {value}",
            collections.get(id).map(String::as_str).unwrap_or(""),
            s(v.get("name")?),
            field(v, "resolvedType")
        ));
    }
    if vars.len() > 60 {
        rows.push(format!(
            "- ... and {} more (see raw/variables.json)",
            vars.len() - 60
        ))
    }
    Some(rows)
}
#[path = "figma_markdown_candidates.rs"]
mod candidates;
#[path = "figma_markdown_layout.rs"]
mod layout;

pub(super) fn render(
    summary: &Value,
    warnings: &[String],
) -> [(&'static str, Option<Vec<String>>); 3] {
    [
        ("markdown_tokens", token_lines(summary)),
        ("markdown_candidates", candidates::render(summary)),
        ("markdown_layout", layout::render(summary, warnings)),
    ]
}

fn token_lines(summary: &Value) -> Option<Vec<String>> {
    let mut lines = Vec::new();
    let tokens = obj(summary, "designTokens")?;
    for (key, title) in [
        ("colorStyles", "Design Tokens — Color Styles"),
        ("textStyles", "Design Tokens — Text Styles"),
        ("effectStyles", "Design Tokens — Effect Styles"),
    ] {
        section(&mut lines, title, rows(tokens, key, false)?);
    }
    section(
        &mut lines,
        "Design Tokens — Variables",
        variables(obj(tokens, "variables")?)?,
    );
    let refs = obj(summary, "referencedStyles")?;
    for (key, title) in [
        ("colorStyles", "Referenced Color Styles (from node payload)"),
        ("textStyles", "Referenced Text Styles (from node payload)"),
        (
            "effectStyles",
            "Referenced Effect Styles (from node payload)",
        ),
    ] {
        section(&mut lines, title, rows(refs, key, true)?);
    }
    Some(lines)
}
