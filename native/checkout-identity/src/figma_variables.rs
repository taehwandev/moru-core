//! owner: offline Figma variable collections and alias resolution;
//! allowed imports: ordered Python JSON and std collections; forbidden: I/O and providers;
//! callers/tests: guarded Figma variables probe and variable extraction fixtures.
use crate::python_json::{Object, PythonJson, Value};
use std::collections::{HashMap, HashSet};

fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    let mut out = Object::new();
    for (k, v) in pairs {
        out.insert(k.into(), v);
    }
    Value::Object(out)
}
fn field(row: &Value, k: &str) -> Value {
    row.get(k)
        .cloned()
        .unwrap_or_else(|| Value::String(String::new()))
}
fn values<'a>(row: &'a Value, k: &str) -> impl Iterator<Item = &'a Value> {
    row.get(k)
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|o| o.iter().map(|(_, v)| v))
}
fn color_channel(value: &Value) -> Option<f64> {
    match value {
        Value::Number(n) => n.as_float().filter(|v| v.is_finite() && v.abs() < 1e100),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        _ => None,
    }
}
fn hex(raw: &Value) -> Option<Value> {
    if ["r", "g", "b"].iter().any(|k| raw.get(k).is_none()) {
        return Some(Value::Null);
    }
    let channel = |v: f64| (v * 255.0).round_ties_even().clamp(0.0, 255.0) as u8;
    let mut out = String::from("#");
    for key in ["r", "g", "b"] {
        out.push_str(&format!("{:02X}", channel(color_channel(&raw[key])?)))
    }
    let alpha = match &raw["a"] {
        Value::Null => 1.0,
        v => color_channel(v)?,
    };
    if alpha < 0.995 {
        out.push_str(&format!("{:02X}", channel(alpha)))
    }
    Some(Value::String(out))
}
fn collection(row: &Value) -> Option<Value> {
    row.as_object()?;
    let mut modes = Vec::new();
    if let Some(raw) = row.get("modes") {
        for m in raw.as_array()?.iter().filter(|m| m.is_object()) {
            modes.push(object([
                ("modeId", field(m, "modeId")),
                ("name", field(m, "name")),
            ]));
        }
    }
    Some(object([
        ("id", field(row, "id")),
        ("name", field(row, "name")),
        ("modes", Value::Array(modes)),
        ("defaultModeId", field(row, "defaultModeId")),
    ]))
}
fn variable(row: &Value) -> Option<Value> {
    row.as_object()?;
    let mut modes = Object::new();
    if let Some(raw) = row.get("valuesByMode") {
        for (mode, v) in raw.as_object()?.iter() {
            let projected = if v["type"].as_str() == Some("VARIABLE_ALIAS") {
                let id = field(v, "id");
                object([("alias", id.clone()), ("aliasId", id)])
            } else if v.is_object() && row["resolvedType"].as_str() == Some("COLOR") {
                object([("hex", hex(v)?), ("raw", v.clone())])
            } else {
                if v.get("aliasId").is_some_and(PythonJson::truthy) {
                    return None;
                }
                v.clone()
            };
            modes.insert(mode.clone(), projected);
        }
    }
    Some(object([
        ("id", field(row, "id")),
        ("name", field(row, "name")),
        ("resolvedType", field(row, "resolvedType")),
        ("collectionId", field(row, "variableCollectionId")),
        ("valuesByMode", Value::Object(modes)),
    ]))
}
struct Lookup<'a> {
    variables: HashMap<String, &'a Value>,
    collections: HashMap<String, String>,
    defaults: HashMap<String, String>,
    hops: usize,
}
impl<'a> Lookup<'a> {
    fn new(vars: &'a [Value], collections: &[Value]) -> Self {
        let mut lookup = Self {
            variables: HashMap::new(),
            collections: HashMap::new(),
            defaults: HashMap::new(),
            hops: 65536,
        };
        for c in collections {
            let id = PythonJson::string(&c["id"]);
            lookup
                .collections
                .insert(id.clone(), PythonJson::string(&c["name"]));
            if PythonJson::truthy(&c["id"]) {
                lookup
                    .defaults
                    .insert(id, PythonJson::string(&c["defaultModeId"]));
            }
        }
        for v in vars {
            if PythonJson::truthy(&v["id"]) {
                lookup.variables.insert(PythonJson::string(&v["id"]), v);
            }
        }
        lookup
    }
    fn name(&self, id: &str) -> String {
        let Some(v) = self.variables.get(id) else {
            return id.into();
        };
        let collection = self
            .collections
            .get(&PythonJson::string(&v["collectionId"]))
            .map(String::as_str)
            .unwrap_or("");
        let name = PythonJson::string(&v["name"]);
        let display = [collection, &name]
            .into_iter()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("/");
        if display.is_empty() {
            id.into()
        } else {
            display
        }
    }
    fn terminal(&mut self, mut id: String, mode: &str) -> Option<Option<&'a Value>> {
        let mut seen = HashSet::new();
        loop {
            self.hops = self.hops.checked_sub(1)?;
            if !seen.insert(id.clone()) {
                return Some(None);
            }
            if seen.len() > 128 {
                return None;
            }
            let Some(v) = self.variables.get(&id).copied() else {
                return Some(None);
            };
            let modes = v["valuesByMode"].as_object()?;
            let default = self.defaults.get(&PythonJson::string(&v["collectionId"]));
            let chosen = modes
                .get(mode)
                .filter(|v| !matches!(v, Value::Null))
                .or_else(|| {
                    modes
                        .get(default.filter(|k| !k.is_empty())?)
                        .filter(|v| !matches!(v, Value::Null))
                })
                .or_else(|| modes.iter().next().map(|(_, value)| value));
            let Some(value) = chosen else {
                return Some(None);
            };
            if !PythonJson::truthy(&value["aliasId"]) {
                return Some(Some(value));
            }
            id = PythonJson::string(&value["aliasId"]);
        }
    }
}
pub(super) fn parse(text: &str) -> Option<serde_json::Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input = PythonJson::parse(text)?;
    input.as_object()?;
    let empty = Value::Object(Object::new());
    let meta = input.get("meta").unwrap_or(&empty);
    meta.as_object()?;
    let collections = values(meta, "variableCollections")
        .map(collection)
        .collect::<Option<Vec<_>>>()?;
    let vars = values(meta, "variables")
        .map(variable)
        .collect::<Option<Vec<_>>>()?;
    let mut lookup = Lookup::new(&vars, &collections);
    let mut annotated = Vec::new();
    let mut budget = 1024usize * 1024;
    for v in &vars {
        let mut modes = Object::new();
        for (key, value) in v["valuesByMode"].as_object()?.iter() {
            let mut value = value.clone();
            if PythonJson::truthy(&value["aliasId"]) {
                let id = PythonJson::string(&value["aliasId"]);
                let name = lookup.name(&id);
                budget = budget.checked_sub(name.len())?;
                let Value::Object(ref mut fields) = value else {
                    return None;
                };
                fields.insert("aliasName".into(), Value::String(name));
                if let Some(target) = lookup.terminal(id, key)? {
                    for (src, dst) in [("hex", "resolvedHex"), ("aliasName", "resolvedAliasName")] {
                        if PythonJson::truthy(&target[src]) {
                            let string = target[src].as_str()?;
                            budget = budget.checked_sub(string.len())?;
                            fields.insert(dst.into(), Value::String(string.into()));
                            break;
                        }
                    }
                }
            }
            modes.insert(key.clone(), value);
        }
        let mut entry = v.as_object()?.clone();
        entry.insert("valuesByMode".into(), Value::Object(modes));
        annotated.push(Value::Object(entry));
    }
    let output = object([
        ("collections", Value::Array(collections)),
        ("variables", Value::Array(annotated)),
    ]);
    let encoded = PythonJson::render(&output, false, false)?;
    Some(serde_json::json!({"variables_json":encoded}))
}
