//! Owner: group Figma asset candidates for the deduplicated inventory.
//! Allowed imports: Python JSON/text semantics and read-free case conversion.
//! Forbidden: filesystem access, network and exports. Callers/tests: Figma asset analysis.
use crate::{
    discovery_fs::DiscoveryFs,
    python_json::{Number, Object, PythonJson, Value},
    python_text::PythonText,
};
use serde_json::json;
use std::collections::HashMap;

const GENERIC: &[&str] = &[
    "vector",
    "rectangle",
    "group",
    "union",
    "ellipse",
    "subtract",
    "frame",
    "mask",
    "shape",
    "path",
    "intersect",
    "exclude",
    "line",
];

fn generic(name: &str) -> Option<bool> {
    let text = name.trim_matches(PythonText::whitespace);
    if text.is_empty() {
        return Some(true);
    }
    // Only the first nine characters can affect a prefix match.
    let prefix: String = text.chars().take(9).collect();
    let lower = DiscoveryFs::lower(&prefix)?;
    Some(GENERIC.iter().any(|prefix| lower.starts_with(prefix)))
}

fn present<'a>(row: &'a Value, key: &str) -> Option<&'a Value> {
    row.get(key).filter(|value| PythonJson::truthy(value))
}

struct Group {
    kind: Value,
    image_refs: Option<Value>,
    ids: Vec<Value>,
    first_name: Option<String>,
    specific_name: Option<String>,
    nearest_name: Option<String>,
}

impl Group {
    fn new(candidate: &Value) -> Self {
        Self {
            kind: candidate
                .get("type")
                .cloned()
                .unwrap_or_else(|| Value::String(String::new())),
            image_refs: present(candidate, "imageRefs").cloned(),
            ids: Vec::new(),
            first_name: None,
            specific_name: None,
            nearest_name: None,
        }
    }

    fn add(&mut self, candidate: &Value) -> Option<()> {
        if let Some(id) = present(candidate, "id") {
            self.ids.push(id.clone());
        }
        if self.specific_name.is_none() {
            if let Some(value) = present(candidate, "name") {
                let name = PythonJson::string(value);
                if !generic(&name)? {
                    self.specific_name = Some(name);
                } else if self.first_name.is_none() {
                    self.first_name = Some(name);
                }
            }
        }
        if self.nearest_name.is_none() {
            self.nearest_name = present(candidate, "nearestComponentName").map(PythonJson::string);
        }
        Some(())
    }

    fn finish(self, key: &str) -> Value {
        let mut row = Object::new();
        let unclear = self.specific_name.is_none();
        let representative = self
            .specific_name
            .or_else(|| self.nearest_name.clone())
            .or(self.first_name)
            .unwrap_or_default();
        row.insert("dedupKey".into(), Value::String(key.to_owned()));
        row.insert("name".into(), Value::String(representative));
        row.insert("type".into(), self.kind);
        row.insert(
            "usageCount".into(),
            Value::Number(Number::Integer(self.ids.len().to_string())),
        );
        row.insert("nodeIds".into(), Value::Array(self.ids));
        row.insert("nameUnclear".into(), Value::Bool(unclear));
        if let Some(refs) = self.image_refs {
            row.insert("imageRefs".into(), refs);
        }
        if let Some(nearest) = self.nearest_name {
            row.insert("nearestComponentName".into(), Value::String(nearest));
        }
        Value::Object(row)
    }
}

pub(super) fn build(text: &str) -> Option<serde_json::Value> {
    let input = PythonJson::parse(text)?;
    let mut groups = HashMap::new();
    for candidate in input.as_array()? {
        candidate.as_object()?;
        let key = match present(candidate, "dedupKey").or_else(|| present(candidate, "id")) {
            Some(value) => value.as_str()?,
            None => "",
        };
        groups
            .entry(key)
            .or_insert_with(|| Group::new(candidate))
            .add(candidate)?;
    }
    let mut ordered: Vec<_> = groups.into_iter().collect();
    ordered.sort_by(|(ka, a), (kb, b)| b.ids.len().cmp(&a.ids.len()).then_with(|| ka.cmp(kb)));
    let inventory = Value::Array(
        ordered
            .into_iter()
            .map(|(key, group)| group.finish(key))
            .collect(),
    );
    Some(json!({"assets_json": PythonJson::render(&inventory, false, false)?}))
}
