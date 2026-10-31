mod gauge;
mod location;
mod model;
mod py;
mod quota;

use serde_json::{Map, Value};

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
            serde_json::from_str::<Value>(text).ok()?
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
