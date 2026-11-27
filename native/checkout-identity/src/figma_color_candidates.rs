//! owner: Figma solid color usage and ordered variable bindings; allowed imports:
//! pure paint conversion, Python JSON and counters; forbidden imports: I/O and
//! providers; callers/tests: guarded Figma color analysis and offline fixtures.
use super::paint::Paint;
use crate::python_json::{Number, Object, PythonJson, Value};
use std::{
    cmp::Reverse,
    collections::{HashMap, HashSet},
};

fn field(row: &Value, key: &str) -> String {
    row.get(key).map(PythonJson::string).unwrap_or_default()
}
fn list<'a>(row: &'a Value, key: &str) -> Option<&'a [Value]> {
    match row.get(key) {
        None => Some(&[]),
        Some(v) => Some(v.as_array()?.as_slice()),
    }
}
fn variable_names(vars: &Value, budget: &mut usize) -> Option<HashMap<String, String>> {
    vars.as_object()?;
    let mut collections = HashMap::new();
    for c in list(vars, "collections")? {
        c.as_object()?;
        if PythonJson::truthy(&c["id"]) {
            collections.insert(field(c, "id"), field(c, "name"));
        }
    }
    let mut result = HashMap::new();
    for v in list(vars, "variables")? {
        v.as_object()?;
        let id = field(v, "id");
        if id.is_empty() {
            continue;
        }
        let prefix = collections
            .get(&field(v, "collectionId"))
            .map(String::as_str)
            .unwrap_or("");
        let name = field(v, "name");
        *budget = budget.checked_sub(prefix.len() + name.len() + id.len())?;
        let label = [prefix, &name]
            .into_iter()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("/");
        result.insert(id.clone(), if label.is_empty() { id } else { label });
    }
    Some(result)
}
fn variable_id(value: &Value) -> Option<&str> {
    match value {
        Value::String(s) => (!s.is_empty()).then_some(s),
        Value::Array(a) => a.iter().find_map(variable_id),
        Value::Object(o) => o
            .get("id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .or_else(|| {
                ["color", "variable", "resolvedVariable", "alias"]
                    .iter()
                    .filter_map(|k| o.get(k))
                    .find_map(variable_id)
            }),
        _ => None,
    }
}
fn select(value: &Value, index: usize) -> &Value {
    if let Some(a) = value.as_array() {
        return a.get(index).unwrap_or(&Value::Null);
    }
    value.get(&index.to_string()).unwrap_or(value)
}
fn binding<'a>(node: &'a Value, paint: Option<(&'a Value, usize)>, key: &str) -> Option<&'a str> {
    const CONTAINERS: [&str; 2] = ["boundVariables", "boundVariableIds"];
    if let Some((paint, i)) = paint {
        for container in CONTAINERS
            .iter()
            .filter_map(|k| paint.get(k))
            .filter(|v| v.is_object())
        {
            if let Some(id) = [&container["color"], select(&container[key], i), container]
                .into_iter()
                .find_map(variable_id)
            {
                return Some(id);
            }
        }
    }
    for container in CONTAINERS
        .iter()
        .filter_map(|k| node.get(k))
        .filter(|v| v.is_object())
    {
        let keys = if key == "backgroundColor" {
            &["backgroundColor", "background", "fills"][..]
        } else {
            std::slice::from_ref(&key)
        };
        for k in keys {
            let value = &container[k];
            if let Some(id) = variable_id(paint.map_or(value, |(_, i)| select(value, i))) {
                return Some(id);
            }
        }
    }
    None
}
#[derive(Default)]
struct OrderedNames {
    seen: HashSet<String>,
    values: Vec<String>,
}
impl OrderedNames {
    fn add(&mut self, name: &str) {
        if !self.seen.contains(name) {
            self.seen.insert(name.into());
            self.values.push(name.into());
        }
    }
}
#[derive(Default)]
struct Color {
    count: usize,
    sources: Vec<String>,
    names: OrderedNames,
    ids: OrderedNames,
}
fn strings(v: Vec<String>) -> Value {
    Value::Array(v.into_iter().map(Value::String).collect())
}

pub(super) fn summarize(nodes: &[Value], parsed_variables: &Value) -> Option<Vec<Value>> {
    let mut budget = 4usize * 1024 * 1024;
    let labels = variable_names(parsed_variables, &mut budget)?;
    let mut colors = HashMap::<String, (usize, Color)>::new();
    for node in nodes {
        node.as_object()?;
        let name = field(node, "name");
        let mut record = |hex: String, key: &str, id: Option<&str>| -> Option<()> {
            if hex.len() == 9 && hex.ends_with("00") {
                return Some(());
            }
            let order = colors.len();
            let row = &mut colors
                .entry(hex)
                .or_insert_with(|| (order, Color::default()))
                .1;
            row.count += 1;
            if row.sources.len() < 8 {
                budget = budget.checked_sub(name.len() + key.len())?;
                let source = format!("{name} ({key})");
                if !row.sources.contains(&source) {
                    row.sources.push(source);
                }
            }
            if let Some(id) = id {
                budget = budget.checked_sub(id.len())?;
                row.ids.add(id);
                if let Some(label) = labels.get(id) {
                    budget = budget.checked_sub(label.len())?;
                    row.names.add(label);
                }
            }
            Some(())
        };
        for key in ["fills", "strokes"] {
            if let Some(paints) = node.get(key).filter(|v| PythonJson::truthy(v)) {
                for (i, p) in paints.as_array()?.iter().enumerate() {
                    if matches!(p["visible"], Value::Bool(false))
                        || p["type"].as_str() != Some("SOLID")
                    {
                        continue;
                    }
                    if let Some(hex) = Paint::solid(&p["color"], &p["opacity"])? {
                        record(hex, key, binding(node, Some((p, i)), key))?;
                    }
                }
            }
        }
        let bg = &node["backgroundColor"];
        if bg.is_object() {
            if let Some(hex) = Paint::solid(bg, &Value::Null)? {
                record(
                    hex,
                    "backgroundColor",
                    binding(node, None, "backgroundColor"),
                )?;
            }
        }
    }
    let mut colors: Vec<_> = colors.into_iter().collect();
    colors.sort_unstable_by_key(|(_, (index, row))| (Reverse(row.count), *index));
    Some(
        colors
            .into_iter()
            .map(|(hex, (_, row))| {
                let mut result = Object::new();
                for (k, v) in [
                    ("hex", Value::String(hex)),
                    (
                        "count",
                        Value::Number(Number::Integer(row.count.to_string())),
                    ),
                    ("sources", strings(row.sources)),
                    ("boundVariableNames", strings(row.names.values)),
                    ("boundVariableIds", strings(row.ids.values)),
                ] {
                    result.insert(k.into(), v);
                }
                Value::Object(result)
            })
            .collect(),
    )
}
