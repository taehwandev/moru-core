//! owner: BehaviorEvalError; allowed imports: PythonJson, PythonText and std; forbidden imports:
//! filesystem, process and provider access; callers/tests: offline grader schema
//! and CLI; verification: public diagnostic and Python fallback parity.

use crate::{
    python_json::{Number, PythonJson, Value},
    python_text::PythonText,
};

pub(crate) enum BehaviorEvalError {
    Stable(String),
    Unicode(String),
    Reference(String),
}

impl BehaviorEvalError {
    pub(crate) fn text(prefix: &str, text: &str) -> Self {
        let detail = format!("{prefix}{}", PythonText::repr(text));
        if text.is_ascii() {
            Self::Stable(detail)
        } else {
            Self::Unicode(detail)
        }
    }

    pub(crate) fn value(prefix: &str, value: &Value) -> Self {
        let detail = format!("{prefix}{}", PythonJson::repr(value));
        match Self::requires_unicode(value) {
            Some(false) => Self::Stable(detail),
            Some(true) => Self::Unicode(detail),
            None => Self::Reference(detail),
        }
    }

    /// Finite float repr depends on the interpreter's formatting contract.
    /// Return None if any nested value has that dependency.
    fn requires_unicode(value: &Value) -> Option<bool> {
        match value {
            Value::Number(Number::Float(value)) if value.is_finite() => None,
            Value::String(value) => Some(!value.is_ascii()),
            Value::Array(values) => values.iter().try_fold(false, |unicode, value| {
                Some(Self::requires_unicode(value)? || unicode)
            }),
            Value::Object(values) => values.iter().try_fold(false, |unicode, (key, value)| {
                Some(Self::requires_unicode(value)? || !key.is_ascii() || unicode)
            }),
            _ => Some(false),
        }
    }
}

impl From<&'static str> for BehaviorEvalError {
    fn from(detail: &'static str) -> Self {
        Self::Stable(detail.to_owned())
    }
}

impl From<String> for BehaviorEvalError {
    fn from(detail: String) -> Self {
        Self::Reference(detail)
    }
}
