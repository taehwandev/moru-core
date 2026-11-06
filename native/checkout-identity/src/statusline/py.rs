use crate::python_json::{Object as Map, PythonJson, Value};
use crate::python_text::PythonText;

/// Python semantics shared by the statusline modules.
pub(crate) struct Py;

impl Py {
    pub(crate) fn strip(text: &str) -> &str {
        text.trim_matches(PythonText::whitespace)
    }

    pub(crate) fn truthy(value: &Value) -> bool {
        PythonJson::truthy(value)
    }

    /// Python `a.get(k1) or a.get(k2) or ...`: first truthy value, else None.
    pub(crate) fn pick<'a>(object: &'a Map, keys: &[&str]) -> Option<&'a Value> {
        keys.iter()
            .filter_map(|key| object.get(*key))
            .find(|value| Self::truthy(value))
    }
}
