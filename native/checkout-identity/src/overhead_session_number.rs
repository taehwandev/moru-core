//! owner: SessionNumber; allowed imports: shared PythonJson/PythonText/std;
//! forbidden imports: I/O; callers/tests: OverheadSession; verification: Python int and ID equality.
use crate::{
    python_json::{Number, PythonJson, Value},
    python_text::PythonText,
};
pub(super) struct SessionNumber;
impl SessionNumber {
    pub(super) fn integer(value: &Value) -> Option<i64> {
        if !PythonJson::truthy(value) {
            return Some(0);
        }
        match value {
            Value::Bool(v) => Some(i64::from(*v)),
            Value::Number(Number::Integer(s)) => s.parse().ok(),
            Value::Number(Number::Float(v)) => {
                if !v.is_finite() || *v < i64::MIN as f64 || *v >= -(i64::MIN as f64) {
                    None
                } else {
                    Some(v.trunc() as i64)
                }
            }
            Value::String(s) => Self::string(s),
            _ => None,
        }
    }
    fn string(text: &str) -> Option<i64> {
        let limit = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
            .unwrap_or("0")
            .parse()
            .ok()?;
        Self::string_with_limit(text, limit)
    }
    pub(super) fn string_with_limit(text: &str, limit: usize) -> Option<i64> {
        let chars: Vec<_> = text
            .trim_matches(|c: char| {
                matches!(c, ' ' | '\t' | '\n' | '\r' | '\x0b' | '\x0c')
                    || (!c.is_ascii() && PythonText::whitespace(c))
            })
            .chars()
            .collect();
        let mut out = String::new();
        let mut previous = false;
        let mut digits = 0usize;
        for (i, c) in chars.iter().copied().enumerate() {
            if i == 0 && matches!(c, '+' | '-') {
                out.push(c);
                continue;
            }
            if c == '_' && previous && chars.get(i + 1).is_some_and(|c| PythonText::decimal(*c)) {
                previous = false;
                continue;
            }
            out.push(char::from(b'0' + PythonText::decimal_value(c)?));
            digits += 1;
            // Python counts every decimal digit, including Unicode leading zeroes.
            if limit > 0 && digits > limit {
                return None;
            }
            previous = true;
        }
        if !previous {
            return None;
        }
        out.parse().ok()
    }
    pub(super) fn identity(value: &Value) -> Option<String> {
        Some(match value {
            Value::Null => "null".into(),
            Value::String(s) => format!("str:{s}"),
            Value::Bool(v) => format!("int:{}", u8::from(*v)),
            Value::Number(Number::Integer(s)) => format!("int:{s}"),
            Value::Number(Number::Float(v)) if v.is_finite() && v.fract() == 0.0 => format!(
                "int:{}",
                if *v == 0.0 {
                    "0".into()
                } else {
                    format!("{v:.0}")
                }
            ),
            Value::Number(Number::Float(v)) if v.is_nan() => "nan-constant".into(),
            Value::Number(Number::Float(v)) => format!("float:{:x}", v.to_bits()),
            _ => return None,
        })
    }
}
