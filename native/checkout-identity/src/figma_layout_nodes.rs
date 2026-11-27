//! owner: ordered flattening and visibility of overlapping Figma layout trees;
//! allowed imports: Python JSON, Figma numeric and paint projection, node IDs;
//! forbidden imports: I/O and provider APIs; callers/tests: guarded layout probe.
use super::{number::round_number, target::Target};
use crate::python_json::{Number, Object, PythonJson, Value};
use std::collections::{HashMap, HashSet};
#[path = "figma_rendered_paints.rs"]
mod paints;

const FIELDS: &[&str] = &[
    "layoutMode",
    "layoutWrap",
    "primaryAxisAlignItems",
    "counterAxisAlignItems",
    "counterAxisAlignContent",
    "primaryAxisSizingMode",
    "counterAxisSizingMode",
    "layoutPositioning",
    "layoutAlign",
    "layoutGrow",
    "layoutSizingHorizontal",
    "layoutSizingVertical",
    "itemSpacing",
    "counterAxisSpacing",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "cornerRadius",
    "rectangleCornerRadii",
    "minWidth",
    "maxWidth",
    "minHeight",
    "maxHeight",
    "constraints",
    "clipsContent",
    "overflowDirection",
    "opacity",
    "blendMode",
    "isMask",
    "maskType",
    "rotation",
    "relativeTransform",
    "size",
    "strokeWeight",
    "strokeAlign",
    "individualStrokeWeights",
    "strokeDashes",
    "visible",
];

fn round_value(value: &Value) -> Option<Value> {
    Some(match value {
        Value::Number(n) => Value::Number(round_number(n)?),
        Value::Array(a) => Value::Array(a.iter().map(round_value).collect::<Option<_>>()?),
        Value::Object(o) => {
            let mut out = Object::new();
            for (k, v) in o.iter() {
                out.insert(k.clone(), round_value(v)?);
            }
            Value::Object(out)
        }
        v => v.clone(),
    })
}
fn field(node: &Value, k: &str) -> Value {
    node.get(k)
        .cloned()
        .unwrap_or_else(|| Value::String(String::new()))
}
fn reasons_list(reasons: &[String]) -> Value {
    Value::Array(reasons.iter().cloned().map(Value::String).collect())
}
fn entry(
    node: &Value,
    id: &str,
    parent: Option<&str>,
    depth: usize,
    reasons: &[String],
) -> Option<Object> {
    let mut out = Object::new();
    for (key, val) in [
        ("id", Value::String(id.into())),
        ("name", field(node, "name")),
        ("type", field(node, "type")),
        (
            "parentId",
            parent
                .map(|p| Value::String(p.into()))
                .unwrap_or(Value::Null),
        ),
        ("depth", Value::Number(Number::Integer(depth.to_string()))),
        ("effectiveVisible", Value::Bool(reasons.is_empty())),
    ] {
        out.insert(key.into(), val);
    }
    if !reasons.is_empty() {
        out.insert("visibilityReasons".into(), reasons_list(reasons));
    }
    for key in ["absoluteBoundingBox", "absoluteRenderBounds"] {
        if node[key].as_object().is_some_and(|o| !o.is_empty()) {
            out.insert(key.into(), round_value(&node[key])?);
        }
    }
    for &key in FIELDS {
        if let Some(v) = node.get(key) {
            out.insert(key.into(), round_value(v)?);
        }
    }
    if let Some(c) = node["componentId"].as_str().filter(|s| !s.is_empty()) {
        out.insert("componentId".into(), Value::String(Target::normalize(c)?));
    }
    if let Some(props) = node["componentProperties"].as_object() {
        let mut flat = Object::new();
        for (k, v) in props.iter() {
            if v.is_object() {
                flat.insert(k.clone(), v["value"].clone());
            }
        }
        if !flat.is_empty() {
            out.insert("componentProperties".into(), Value::Object(flat));
        }
    }
    let paints = paints::render(node)?;
    if !paints.is_empty() {
        out.insert("renderedPaints".into(), Value::Object(paints));
    }
    Some(out)
}
struct Layout {
    rows: Vec<Object>,
    by_id: HashMap<String, usize>,
    budget: usize,
}
impl Layout {
    fn merge(&mut self, index: usize, extra: &[String]) -> Option<()> {
        if extra.is_empty() {
            return Some(());
        }
        let row = &mut self.rows[index];
        let mut seen = HashSet::new();
        let mut reasons = Vec::new();
        if let Some(previous) = row.get("visibilityReasons") {
            for v in previous.as_array()? {
                let r = v.as_str()?;
                self.budget = self.budget.checked_sub(r.len() + 1)?;
                if seen.insert(r) {
                    reasons.push(r.to_owned());
                }
            }
        }
        for r in extra {
            if seen.insert(r) {
                reasons.push(r.clone());
            }
        }
        row.insert("effectiveVisible".into(), Value::Bool(false));
        row.insert("visibilityReasons".into(), reasons_list(&reasons));
        Some(())
    }
    fn walk(
        &mut self,
        node: &Value,
        parent: Option<&str>,
        depth: usize,
        ancestors: &mut Vec<String>,
    ) -> Option<()> {
        if !node.is_object() {
            return Some(());
        }
        if depth > 128 {
            return None;
        }
        let raw = node.get("id").map(PythonJson::string).unwrap_or_default();
        let id = Target::normalize(&raw)?;
        let hidden = matches!(node["visible"], Value::Bool(false));
        let transparent = match &node["opacity"] {
            Value::Number(n) => n.as_float()? <= 0.0,
            _ => false,
        };
        let len = ancestors.len();
        if hidden {
            ancestors.push("self.visible=false".into());
        }
        if transparent {
            ancestors.push("self.opacity=0".into());
        }
        self.budget = self.budget.checked_sub(
            ancestors.iter().map(|s| s.len() + 1).sum::<usize>() + parent.map_or(0, str::len) + 48,
        )?;
        if let Some(&index) = self.by_id.get(&id) {
            self.merge(index, ancestors)?;
        } else {
            let row = entry(node, &id, parent, depth, ancestors)?;
            if !id.is_empty() {
                self.by_id.insert(id.clone(), self.rows.len());
            }
            self.rows.push(row);
        }
        ancestors.truncate(len);
        let current = if id.is_empty() {
            parent
        } else {
            Some(id.as_str())
        };
        if let Some(children) = node.get("children").filter(|v| PythonJson::truthy(v)) {
            let children = children.as_array()?;
            if hidden || transparent {
                let label = if id.is_empty() {
                    PythonJson::string(&field(node, "name"))
                } else {
                    id.clone()
                };
                let label = if label.is_empty() { "unknown" } else { &label };
                if hidden {
                    ancestors.push(format!("ancestor:{label}.visible=false"));
                }
                if transparent {
                    ancestors.push(format!("ancestor:{label}.opacity=0"));
                }
            }
            for child in children {
                self.walk(child, current, depth + 1, ancestors)?;
            }
            ancestors.truncate(len);
        }
        Some(())
    }
}
pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input = PythonJson::parse(text)?;
    let mut layout = Layout {
        rows: Vec::new(),
        by_id: HashMap::new(),
        budget: 2 * 1024 * 1024,
    };
    for document in input.as_array()? {
        layout.walk(document, None, 0, &mut Vec::new())?;
    }
    let rows = Value::Array(layout.rows.into_iter().map(Value::Object).collect());
    Some(serde_json::json!({"layout_nodes_json":PythonJson::render(&rows,false,false)?}))
}
