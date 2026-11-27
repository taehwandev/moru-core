//! owner: ordered Figma text style frequencies and representative samples;
//! allowed imports: pure text style projection, Python JSON and counters;
//! forbidden imports: I/O and providers; callers/tests: guarded style summary.
use crate::python_json::{Number, Object, PythonJson, Value};
use std::{cmp::Reverse, collections::HashMap};

struct Group {
    style: Object,
    count: usize,
    samples: Vec<String>,
}
struct Styles {
    indices: HashMap<String, usize>,
    groups: Vec<Group>,
    remaining: usize,
}
impl Styles {
    fn add(&mut self, base: &Object, overrides: Option<&Object>, sample: &str) -> Option<()> {
        let style = super::text_style::project(base, overrides)?;
        // The projector emits a fixed key order. For scalar fields this groups
        // exactly the same rows as Python's sort_keys=True serialization.
        if style.iter().any(|(_, v)| v.is_object() || v.is_array()) {
            return None;
        }
        let value = Value::Object(style);
        let key = PythonJson::render(&value, false, false)?;
        self.remaining = self.remaining.checked_sub(key.len())?;
        let Value::Object(style) = value else {
            return None;
        };
        let index = match self.indices.entry(key) {
            std::collections::hash_map::Entry::Occupied(entry) => *entry.get(),
            std::collections::hash_map::Entry::Vacant(entry) => {
                let index = self.groups.len();
                entry.insert(index);
                self.groups.push(Group {
                    style,
                    count: 0,
                    samples: Vec::new(),
                });
                index
            }
        };
        let group = &mut self.groups[index];
        group.count += 1;
        // Reference checks the original sample against the stored prefixes.
        if !sample.is_empty()
            && group.samples.len() < 5
            && !group.samples.iter().any(|s| s == sample)
        {
            group.samples.push(sample.chars().take(80).collect());
        }
        Some(())
    }
    fn node(&mut self, node: &Value) -> Option<()> {
        node.as_object()?;
        if node["type"].as_str() != Some("TEXT") {
            return Some(());
        }
        let Some(base) = node["style"].as_object() else {
            return Some(());
        };
        let sample = node
            .get("characters")
            .or_else(|| node.get("name"))
            .map(PythonJson::string)
            .unwrap_or_default()
            .replace('\n', " ");
        self.add(base, None, &sample)?;
        if let Some(table) = node["styleOverrideTable"].as_object() {
            for (_, v) in table.iter() {
                if let Some(overrides) = v.as_object() {
                    self.add(base, Some(overrides), &sample)?;
                }
            }
        }
        Some(())
    }
}
pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input = PythonJson::parse(text)?;
    let mut styles = Styles {
        indices: HashMap::new(),
        groups: Vec::new(),
        remaining: 8 * 1024 * 1024,
    };
    for node in input.as_array()? {
        styles.node(node)?;
    }
    // Stable sort retains the first observation for equal frequencies.
    styles.groups.sort_by_key(|g| Reverse(g.count));
    let mut rows = Vec::new();
    for mut group in styles.groups {
        group.style.insert(
            "count".into(),
            Value::Number(Number::Integer(group.count.to_string())),
        );
        group.style.insert(
            "samples".into(),
            Value::Array(group.samples.into_iter().map(Value::String).collect()),
        );
        rows.push(Value::Object(group.style));
    }
    Some(serde_json::json!({"rows_json":PythonJson::render(&Value::Array(rows),false,false)?}))
}
