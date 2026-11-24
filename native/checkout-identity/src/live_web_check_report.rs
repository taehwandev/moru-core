//! owner: live-web check status and output formatting.
//! allowed imports: Python-compatible JSON and text formatting only.
//! forbidden imports: log reads or writes, workflow or access decisions.
//! callers/tests: live-web check lookup and Python CLI parity fixtures.
//! verification: exact JSON, missing and malformed views, status and box rounding.
use crate::python_json::{Number, PythonJson, Value};
use serde_json::{json, Value as Json};

pub(super) struct LiveWebCheckReport;

impl LiveWebCheckReport {
    pub(super) fn render(check: Option<&Value>, options: &Json) -> Option<Json> {
        let (status, code) = match check {
            None => ("none", 5),
            Some(check) if Self::problems(check) => ("problems", 4),
            Some(_) => ("ok", 0),
        };
        let output = if options.get("json")?.as_bool()? {
            let check = PythonJson::render(check.unwrap_or(&Value::Null), false, true)?;
            format!(r#"{{"status": "{status}", "check": {check}}}"#)
        } else if let Some(check) = check {
            Self::describe(check)?
        } else {
            let files = options
                .get("files")?
                .as_array()?
                .iter()
                .map(Json::as_str)
                .collect::<Option<Vec<_>>>()?;
            if files.is_empty() {
                "no check yet".to_owned()
            } else {
                format!("no check yet for {}", files.join(", "))
            }
        };
        Some(json!({"code": code, "output": output}))
    }

    fn reload_failed(check: &Value) -> bool {
        matches!(check.get("reloadFailed"), Some(Value::Bool(true)))
    }

    fn problems(check: &Value) -> bool {
        !Self::array(check.get("errors")).is_empty() || Self::reload_failed(check)
    }

    fn array(value: Option<&Value>) -> &[Value] {
        value
            .and_then(Value::as_array)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    fn describe(check: &Value) -> Option<String> {
        let files = Self::array(check.get("files"))
            .iter()
            .map(PythonJson::string)
            .collect::<Vec<_>>()
            .join(", ");
        let files = if files.is_empty() {
            "(no files)"
        } else {
            &files
        };
        let views = Self::array(check.get("views"));
        let views = if views.is_empty() {
            "no views".to_owned()
        } else {
            views
                .iter()
                .map(Self::view)
                .collect::<Option<Vec<_>>>()?
                .join(", ")
        };
        let errors = Self::array(check.get("errors"));
        let mut error_text = format!("errors {}", errors.len());
        if let Some(first) = errors.first() {
            error_text.push_str(": ");
            error_text.push_str(&PythonJson::string(first));
        }
        let reload = if Self::reload_failed(check) {
            "FAILED"
        } else {
            "ok"
        };
        let time = check
            .get("time")
            .map(PythonJson::string)
            .unwrap_or_else(|| "?".into());
        Some(format!(
            "check {time} {files}: {views}; {error_text}; reload {reload}"
        ))
    }

    fn view(view: &Value) -> Option<String> {
        if !view.is_object() {
            return Some("?".into());
        }
        let count = view.get("elements");
        let (count, singular) = match count {
            Some(Value::Number(Number::Integer(n))) => (n.clone(), n == "1"),
            Some(Value::Bool(value)) => (if *value { "True" } else { "False" }.to_owned(), *value),
            _ => ("0".to_owned(), false),
        };
        let viewport = view
            .get("viewport")
            .filter(|value| PythonJson::truthy(value))
            .map(PythonJson::string)
            .unwrap_or_else(|| "?".into());
        let plural = if singular { "" } else { "s" };
        let mut text = format!("{viewport} {count} element{plural}");
        if let Some(first) = Self::array(view.get("boxes"))
            .first()
            .and_then(Value::as_array)
        {
            if let [_, _, width, height] = first.as_slice() {
                if first
                    .iter()
                    .all(|value| matches!(value, Value::Bool(_) | Value::Number(_)))
                {
                    text.push_str(&format!(
                        " ({}x{})",
                        Self::dimension(width)?,
                        Self::dimension(height)?
                    ));
                }
            }
        }
        Some(text)
    }

    fn dimension(value: &Value) -> Option<String> {
        match value {
            Value::Bool(value) => Some(u8::from(*value).to_string()),
            Value::Number(Number::Integer(value)) => Some(value.clone()),
            Value::Number(Number::Float(value)) if value.is_finite() => {
                let rounded = value.round_ties_even();
                if rounded == 0.0 {
                    Some("0".into())
                } else {
                    Some(format!("{rounded:.0}"))
                }
            }
            _ => None,
        }
    }
}
