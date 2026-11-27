//! Owner: Figma gradient counts and source attribution. Allowed imports: paint and ordered JSON.
//! Forbidden: filesystem and network. Verification: gradient candidate parity fixtures.
use super::paint::Paint;
use crate::python_json::{Number, Object, PythonJson, Value};
use std::{cmp::Reverse, collections::HashMap};

struct Candidate {
    paint: Object,
    count: usize,
    sources: Vec<String>,
}

pub(super) fn summarize(nodes: &[Value]) -> Option<Vec<Value>> {
    let mut positions = HashMap::new();
    let mut groups: Vec<Candidate> = Vec::new();
    let mut source_bytes = 0;
    for node in nodes {
        node.as_object()?;
        let name = node.get("name").map(PythonJson::string).unwrap_or_default();
        for field in ["background", "fills", "strokes"] {
            let paints = &node[field];
            if !PythonJson::truthy(paints) {
                continue;
            }
            let mut source = None;
            for paint in paints.as_array()? {
                let Some(gradient) = Paint::gradient(paint)? else {
                    continue;
                };
                // The paint projection supplies a fixed key order at every object level.
                let key = PythonJson::render(&gradient, false, false)?;
                let index = *positions.entry(key).or_insert_with(|| groups.len());
                if index == groups.len() {
                    let Value::Object(paint) = gradient else {
                        return None;
                    };
                    groups.push(Candidate {
                        paint,
                        count: 0,
                        sources: Vec::new(),
                    });
                }
                let group = &mut groups[index];
                group.count += 1;
                if group.sources.len() < 8 {
                    let label = source.get_or_insert_with(|| format!("{name} ({field})"));
                    if !group.sources.contains(label) {
                        source_bytes += label.len();
                        if source_bytes > 1024 * 1024 {
                            return None;
                        }
                        group.sources.push(label.clone());
                    }
                }
            }
        }
    }
    groups.sort_by_key(|group| Reverse(group.count));
    Some(
        groups
            .into_iter()
            .map(|mut group| {
                group.paint.insert(
                    "count".into(),
                    Value::Number(Number::Integer(group.count.to_string())),
                );
                group.paint.insert(
                    "sources".into(),
                    Value::Array(group.sources.into_iter().map(Value::String).collect()),
                );
                Value::Object(group.paint)
            })
            .collect(),
    )
}
