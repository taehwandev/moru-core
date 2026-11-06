mod gauge;
mod location;
mod model;
mod py;
mod quota;
#[cfg(test)]
#[path = "renderer_tests.rs"]
mod tests;

use crate::python_json::{Object as Map, ParseOutcome, PythonJson, Value};

use location::Location;
use model::ModelName;
use py::Py;
use quota::Quota;

pub(crate) struct Renderer;

impl Renderer {
    /// Returns None when the Python compatibility path must be used.
    pub(crate) fn render(payload: &str, home: &str, color: bool) -> Option<String> {
        // json.loads accepts only JSON whitespace, unlike str.strip().
        let text = payload.trim_matches([' ', '\t', '\r', '\n']);
        let root = if text.is_empty() {
            Value::Object(Map::new())
        } else {
            match PythonJson::parse_outcome(text) {
                ParseOutcome::Value(value) => value,
                ParseOutcome::Invalid => Value::Object(Map::new()),
                ParseOutcome::Unsupported => return None,
            }
        };
        let Value::Object(root) = root else {
            return Some(String::new());
        };
        let parts = [
            ModelName::resolve(&root)?,
            Location::resolve(&root, home, color)?,
            Quota::render(&root, color)?,
        ];
        let shown: Vec<&str> = parts
            .iter()
            .filter(|part| !part.is_empty())
            .map(String::as_str)
            .collect();
        Some(shown.join(" · "))
    }

    pub(crate) fn strip(text: &str) -> &str {
        Py::strip(text)
    }
}
