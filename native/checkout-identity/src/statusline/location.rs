use crate::python_json::{Object as Map, PythonJson, Value};

use super::py::Py;

const MAX_CHARS: usize = 34;

pub(crate) struct Location;

impl Location {
    /// Selected truthy values use Python str(), including nested collection representations.
    pub(crate) fn resolve(root: &Map, home: &str, color: bool) -> Option<String> {
        let workspace = match root.get("workspace") {
            Some(Value::Object(workspace)) => Py::pick(workspace, &["project_dir", "current_dir"]),
            _ => None,
        };
        let selected = workspace.or_else(|| Py::pick(root, &["cwd"]));
        let path = match selected {
            None => return Some(String::new()),
            Some(value) => PythonJson::string(value),
        };
        let shown = Self::shorten(Self::fold(&path, home));
        Some(if color {
            format!("\x1b[34m{shown}\x1b[0m")
        } else {
            shown
        })
    }

    fn fold(path: &str, home: &str) -> String {
        if home.is_empty() {
            return path.to_string();
        }
        if path == home {
            return "~".to_string();
        }
        if path.starts_with(&format!("{home}/")) {
            return format!("~{}", &path[home.len()..]);
        }
        path.to_string()
    }

    fn shorten(path: String) -> String {
        if path.chars().count() <= MAX_CHARS {
            return path;
        }
        let parts: Vec<&str> = path.split('/').collect();
        if parts.len() <= 4 {
            return path;
        }
        format!(
            "{}/{}/{}/…/{}",
            parts[0],
            parts[1],
            parts[2],
            parts[parts.len() - 1]
        )
    }
}
