//! owner: first-seen Figma node ancestry and bounded asset fallback projection;
//! allowed imports: ordered Python JSON, node IDs and collections; forbidden:
//! filesystem and network; callers/tests: guarded enriched asset candidate probe.
use super::Target;
use crate::python_json::{Object, PythonJson, Value};
use std::{collections::HashMap, rc::Rc};

struct Node {
    parent: Option<Rc<str>>,
    name: String,
    component: Option<String>,
}

fn index(documents: &Object) -> Option<HashMap<String, Node>> {
    let mut nodes = HashMap::new();
    for (_, root) in documents.iter() {
        let mut stack = vec![(root, None::<Rc<str>>)];
        while let Some((node, parent)) = stack.pop() {
            node.as_object()?;
            let raw = node.get("id").map(PythonJson::string).unwrap_or_default();
            let id = Target::normalize(&raw)?;
            let current = if id.is_empty() {
                parent
            } else {
                if !nodes.contains_key(&id) {
                    let component = match node["componentId"].as_str().filter(|v| !v.is_empty()) {
                        Some(c) => Some(Target::normalize(c)?),
                        None => None,
                    };
                    nodes.insert(
                        id.clone(),
                        Node {
                            parent,
                            name: node.get("name").map(PythonJson::string).unwrap_or_default(),
                            component,
                        },
                    );
                }
                Some(Rc::from(id))
            };
            if let Some(children) = node.get("children").filter(|v| PythonJson::truthy(v)) {
                for child in children.as_array()?.iter().rev().filter(|v| v.is_object()) {
                    stack.push((child, current.clone()));
                }
            }
        }
    }
    Some(nodes)
}
pub(super) fn enrich(candidates: &mut [Value], documents: &Value, labels: &Value) -> Option<()> {
    let documents = documents.as_object()?;
    let labels = labels.as_object()?;
    let nodes = index(documents)?;
    let mut budget = 1024usize * 1024;
    for candidate in candidates {
        let id = candidate.get("id")?.as_str()?;
        let mut cursor = nodes.get(id).and_then(|node| node.parent.as_deref());
        let mut chain = Vec::new();
        for _ in 0..3 {
            let Some(parent) = cursor else { break };
            let node = nodes.get(parent)?;
            if !documents.contains_key(parent) {
                budget = budget.checked_sub(parent.len() + node.name.len())?;
                let mut row = Object::new();
                row.insert("id".into(), Value::String(parent.into()));
                row.insert("name".into(), Value::String(node.name.clone()));
                chain.push(Value::Object(row));
            }
            cursor = node.parent.as_deref();
        }
        let mut cursor = Some(id);
        let mut label = None;
        for _ in 0..8 {
            let Some(node) = cursor.and_then(|id| nodes.get(id)) else {
                break;
            };
            if let Some(component) = node.component.as_deref().filter(|id| !id.is_empty()) {
                label = labels
                    .get(component)
                    .filter(|value| PythonJson::truthy(value));
                break;
            }
            cursor = node.parent.as_deref();
        }
        let Value::Object(candidate) = candidate else {
            return None;
        };
        if !chain.is_empty() {
            candidate.insert("renderFallbackIds".into(), Value::Array(chain));
        }
        if let Some(value) = label {
            let name = value.as_str()?;
            budget = budget.checked_sub(name.len())?;
            candidate.insert("nearestComponentName".into(), Value::String(name.into()));
        }
    }
    Some(())
}
