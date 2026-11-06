//! owner: PythonJson; allowed imports: PythonText and private JSON parser/value modules;
//! forbidden imports: process/network/runtime Python; callers/tests: manifests, statusline,
//! callback profiling; verification: shared JSON/coercion and process parity tests.
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
pub(crate) use number::ManifestNumber as Number;
pub(crate) use object::ManifestObject as Object;
pub(crate) use outcome::ParseOutcome;
pub(crate) use value::ManifestValue as Value;

pub(crate) struct PythonJson;
impl PythonJson {
    /// Manifests preserve the reference exception path for every parse failure.
    pub(crate) fn parse(text: &str) -> Option<Value> {
        parser::ManifestParser::parse(text)
    }
    pub(crate) fn parse_outcome(text: &str) -> ParseOutcome {
        parser::ManifestParser::parse_outcome(text)
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
