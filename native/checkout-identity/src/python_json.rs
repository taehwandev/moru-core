//! owner: PythonJson; allowed imports: PythonText and private JSON parser/value modules;
//! forbidden imports: process/network/runtime Python; callers/tests: manifests, statusline,
//! callback profiling; verification: shared JSON/coercion and process parity tests.
#[path = "python_json_input_diagnostic.rs"]
mod input_diagnostic;
#[path = "manifest_number.rs"]
mod number;
#[path = "manifest_object.rs"]
mod object;
#[path = "python_json_outcome.rs"]
mod outcome;
#[path = "manifest_parser.rs"]
mod parser;
#[path = "manifest_value.rs"]
mod value;
use crate::python_text::PythonText;
pub(crate) use input_diagnostic::InputDiagnostic;
pub(crate) use number::ManifestNumber as Number;
pub(crate) use object::ManifestObject as Object;
pub(crate) use outcome::ParseOutcome;
pub(crate) use value::ManifestValue as Value;

pub(crate) struct PythonJson;
impl PythonJson {
    pub(crate) fn render(value: &Value, pretty: bool, ascii: bool) -> Option<String> {
        let mut text = String::new();
        Self::write_json(value, 0, pretty, ascii, &mut text)?;
        Some(text)
    }

    fn number(value: &Number) -> String {
        match value {
            Number::Integer(value) => value.clone(),
            Number::Float(value) if value.is_nan() => "NaN".into(),
            Number::Float(value) if *value == f64::INFINITY => "Infinity".into(),
            Number::Float(value) if *value == f64::NEG_INFINITY => "-Infinity".into(),
            Number::Float(value) => Number::float(*value),
        }
    }

    fn quote(text: &str, ascii: bool) -> Option<String> {
        if ascii {
            PythonText::json_ascii(text)
        } else {
            serde_json::to_string(text).ok()
        }
    }

    fn write_json(
        value: &Value,
        level: usize,
        pretty: bool,
        ascii: bool,
        out: &mut String,
    ) -> Option<()> {
        if level > 128 {
            return None;
        }
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(value) => out.push_str(if *value { "true" } else { "false" }),
            Value::Number(value) => out.push_str(&Self::number(value)),
            Value::String(value) => out.push_str(&Self::quote(value, ascii)?),
            Value::Array(values) => {
                out.push('[');
                for (index, value) in values.iter().enumerate() {
                    Self::item_prefix(out, index, level, pretty);
                    Self::write_json(value, level + 1, pretty, ascii, out)?;
                }
                Self::closing(out, values.is_empty(), level, pretty, ']');
            }
            Value::Object(values) => {
                out.push('{');
                for (index, (key, value)) in values.iter().enumerate() {
                    Self::item_prefix(out, index, level, pretty);
                    out.push_str(&Self::quote(key, ascii)?);
                    out.push_str(": ");
                    Self::write_json(value, level + 1, pretty, ascii, out)?;
                }
                Self::closing(out, values.is_empty(), level, pretty, '}');
            }
        }
        Some(())
    }

    fn item_prefix(out: &mut String, index: usize, level: usize, pretty: bool) {
        if index != 0 {
            out.push(',');
            if !pretty {
                out.push(' ');
            }
        }
        if pretty {
            out.push('\n');
            out.push_str(&"  ".repeat(level + 1));
        }
    }

    fn closing(out: &mut String, empty: bool, level: usize, pretty: bool, character: char) {
        if pretty && !empty {
            out.push('\n');
            out.push_str(&"  ".repeat(level));
        }
        out.push(character);
    }

    pub(crate) fn error(text: &str) -> Option<String> {
        parser::ManifestParser::error(text)
    }
    /// Manifests preserve the reference exception path for every parse failure.
    pub(crate) fn parse(text: &str) -> Option<Value> {
        parser::ManifestParser::parse(text)
    }
    pub(crate) fn parse_outcome(text: &str) -> ParseOutcome {
        parser::ManifestParser::parse_outcome(text)
    }
    pub(crate) fn parse_with_diagnostic(
        text: &str,
        digit_limit: Option<usize>,
        modern_trailing_comma: Option<bool>,
    ) -> Result<Option<Value>, InputDiagnostic> {
        parser::ManifestParser::parse_with_diagnostic(text, digit_limit, modern_trailing_comma)
    }
    pub(crate) fn integer_conversion_failed(text: &str) -> bool {
        parser::ManifestParser::integer_conversion_failed(text)
    }
    pub(crate) fn truthy(value: &Value) -> bool {
        match value {
            Value::Null => false,
            Value::Bool(v) => *v,
            Value::Number(v) => v.truthy(),
            Value::String(v) => !v.is_empty(),
            Value::Array(v) => !v.is_empty(),
            Value::Object(v) => !v.is_empty(),
        }
    }
    pub(crate) fn string(value: &Value) -> String {
        match value {
            Value::Null => "None".into(),
            Value::Bool(v) => if *v { "True" } else { "False" }.into(),
            Value::Number(v) => v.text(),
            Value::String(v) => v.clone(),
            Value::Array(v) => format!(
                "[{}]",
                v.iter().map(Self::repr).collect::<Vec<_>>().join(", ")
            ),
            Value::Object(v) => format!(
                "{{{}}}",
                v.iter()
                    .map(|(k, v)| format!("{}: {}", PythonText::repr(k), Self::repr(v)))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }
    pub(crate) fn repr(value: &Value) -> String {
        if let Value::String(v) = value {
            PythonText::repr(v)
        } else {
            Self::string(value)
        }
    }
}
#[cfg(test)]
#[path = "python_json_tests.rs"]
mod tests;
