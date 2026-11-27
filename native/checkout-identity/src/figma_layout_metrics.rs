//! owner: ordered Figma layout metric distributions; allowed imports: Python
//! JSON, shared Figma rounding and counters; forbidden imports: filesystem
//! and network; callers/tests: guarded layout metrics probe and offline fixtures.
use super::number::round_number;
use crate::python_json::{PythonJson, Value};
use serde_json::{json, Map};
use std::{cmp::Reverse, collections::HashMap};

const NUMERIC: &[&str] = &[
    "itemSpacing",
    "counterAxisSpacing",
    "paddingTop",
    "paddingRight",
    "paddingBottom",
    "paddingLeft",
    "cornerRadius",
    "minWidth",
    "maxWidth",
    "minHeight",
    "maxHeight",
];
const ENUMS: &[&str] = &[
    "layoutMode",
    "primaryAxisAlignItems",
    "counterAxisAlignItems",
    "counterAxisAlignContent",
    "layoutWrap",
    "primaryAxisSizingMode",
    "counterAxisSizingMode",
    "layoutPositioning",
];

#[derive(Default)]
struct Counter {
    // Equal counts retain the order of the first observation.
    counts: HashMap<String, (usize, usize)>,
}
impl Counter {
    fn add(&mut self, key: String) {
        let position = self.counts.len();
        self.counts.entry(key).or_insert((0, position)).0 += 1;
    }
    fn number(&mut self, v: &Value) -> Option<()> {
        if let Value::Number(value) = v {
            self.add(round_number(value)?.text());
        }
        Some(())
    }
    fn rows(self) -> serde_json::Value {
        let mut counts = self.counts.into_iter().collect::<Vec<_>>();
        counts.sort_unstable_by_key(|(_, (count, position))| (Reverse(*count), *position));
        serde_json::Value::Array(
            counts
                .into_iter()
                .map(|(value, (count, _))| json!({"value":value,"count":count}))
                .collect(),
        )
    }
}
pub(super) fn summarize(text: &str) -> Option<serde_json::Value> {
    if text.len() > 1024 * 1024 {
        return None;
    }
    let input = PythonJson::parse(text)?;
    let mut result = Map::new();
    let nodes = input.as_array()?;
    for node in nodes {
        node.as_object()?;
    }
    for &key in NUMERIC.iter().chain(ENUMS) {
        let numeric = NUMERIC.contains(&key);
        let mut counter = Counter::default();
        for node in nodes {
            if key == "cornerRadius" {
                if let Some(radii) = node["rectangleCornerRadii"]
                    .as_array()
                    .filter(|r| r.len() == 4)
                {
                    for radius in radii {
                        counter.number(radius)?;
                    }
                    continue;
                }
            }
            if numeric {
                counter.number(&node[key])?;
            } else if let Some(value) = node[key].as_str().filter(|v| !v.is_empty()) {
                counter.add(value.to_owned());
            }
        }
        if !counter.counts.is_empty() {
            result.insert(key.into(), counter.rows());
        }
    }
    Some(json!({"metrics":result}))
}
