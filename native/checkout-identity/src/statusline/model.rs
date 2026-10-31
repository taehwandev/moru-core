use serde_json::{Map, Value};

use super::py::Py;

pub(crate) struct ModelName;

impl ModelName {
    /// None means a non-string name was selected and Python must decide.
    pub(crate) fn resolve(root: &Map<String, Value>) -> Option<String> {
        match root.get("model") {
            Some(Value::String(name)) => Some(Py::strip(name).to_string()),
            Some(Value::Object(model)) => match Py::pick(model, &["display_name", "id"]) {
                None => Some(String::new()),
                Some(Value::String(name)) => Some(Py::strip(name).to_string()),
                Some(_) => None,
            },
            _ => Some(String::new()),
        }
    }
}
