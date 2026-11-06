use crate::python_json::{Object as Map, PythonJson, Value};

use super::py::Py;

pub(crate) struct ModelName;

impl ModelName {
    /// Dict-selected names use Python str(); non-dict scalar model values stay hidden.
    pub(crate) fn resolve(root: &Map) -> Option<String> {
        match root.get("model") {
            Some(Value::String(name)) => Some(Py::strip(name).to_string()),
            Some(Value::Object(model)) => match Py::pick(model, &["display_name", "id"]) {
                None => Some(String::new()),
                Some(value) => Some(Py::strip(&PythonJson::string(value)).to_string()),
            },
            _ => Some(String::new()),
        }
    }
}
