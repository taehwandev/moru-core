//! owner: ManifestParser; allowed imports: std, scalar decoder and private diagnostics;
//! forbidden imports: process/network; callers/tests: PythonJson; verification: JSON parity.
#[path = "manifest_parser_diagnostic.rs"]
mod diagnostic;
#[path = "manifest_parser_scalar.rs"]
mod scalar;
use super::ParseOutcome;
use super::{object::ManifestObject, value::ManifestValue as Value};
use diagnostic::JsonDiagnostic;
pub(super) struct ManifestParser<'a> {
    text: &'a str,
    offset: usize,
    digit_limit: usize,
    unsupported: bool,
    diagnostic: Option<String>,
}
impl<'a> ManifestParser<'a> {
    pub fn parse(text: &'a str) -> Option<Value> {
        match Self::parse_outcome(text) {
            ParseOutcome::Value(value) => Some(value),
            _ => None,
        }
    }
    fn limit() -> Option<usize> {
        option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
            .unwrap_or("0")
            .parse()
            .ok()
    }
    pub fn parse_outcome(text: &'a str) -> ParseOutcome {
        match Self::limit() {
            Some(limit) => Self::outcome_with_limit(text, limit),
            None => ParseOutcome::Unsupported,
        }
    }
    pub fn error(text: &'a str) -> Option<String> {
        let (parser, _) = Self::inspect(text, Self::limit()?);
        if parser.unsupported {
            None
        } else {
            parser.diagnostic
        }
    }
    #[cfg(test)]
    fn with_limit(text: &'a str, digit_limit: usize) -> Option<Value> {
        match Self::outcome_with_limit(text, digit_limit) {
            ParseOutcome::Value(value) => Some(value),
            _ => None,
        }
    }
    fn outcome_with_limit(text: &'a str, digit_limit: usize) -> ParseOutcome {
        let (parser, value) = Self::inspect(text, digit_limit);
        if parser.unsupported {
            ParseOutcome::Unsupported
        } else {
            value.map_or(ParseOutcome::Invalid, ParseOutcome::Value)
        }
    }
    fn inspect(text: &'a str, digit_limit: usize) -> (Self, Option<Value>) {
        let mut parser = Self {
            text,
            offset: 0,
            digit_limit,
            unsupported: false,
            diagnostic: None,
        };
        if text.starts_with('\u{feff}') {
            parser.fail::<()>("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0);
            return (parser, None);
        }
        let mut value = parser.value(0);
        if value.is_some() {
            parser.space();
            if parser.offset != text.len() {
                parser.fail::<()>("Extra data", parser.offset);
                value = None;
            }
        }
        (parser, value)
    }
    fn fail<T>(&mut self, message: &str, offset: usize) -> Option<T> {
        if self.diagnostic.is_none() {
            self.diagnostic = Some(JsonDiagnostic::syntax(self.text, offset, message));
        }
        None
    }
    fn space(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.offset += 1;
        }
    }
    fn peek(&self) -> Option<u8> {
        self.text.as_bytes().get(self.offset).copied()
    }
    fn take(&mut self, byte: u8) -> Option<()> {
        if self.peek() == Some(byte) {
            self.offset += 1;
            Some(())
        } else {
            None
        }
    }
    fn literal(&mut self, text: &str) -> Option<()> {
        if self.text[self.offset..].starts_with(text) {
            self.offset += text.len();
            Some(())
        } else {
            None
        }
    }
    fn value(&mut self, depth: usize) -> Option<Value> {
        if depth > 128 {
            self.unsupported = true;
            return None;
        }
        self.space();
        match self.peek() {
            Some(b'"') => self.string().map(Value::String),
            Some(b'n') => {
                if self.literal("null").is_some() {
                    Some(Value::Null)
                } else {
                    self.fail("Expecting value", self.offset)
                }
            }
            Some(b't') => {
                if self.literal("true").is_some() {
                    Some(Value::Bool(true))
                } else {
                    self.fail("Expecting value", self.offset)
                }
            }
            Some(b'f') => {
                if self.literal("false").is_some() {
                    Some(Value::Bool(false))
                } else {
                    self.fail("Expecting value", self.offset)
                }
            }
            Some(b'[') => self.array(depth),
            Some(b'{') => self.object(depth),
            _ => self.number().map(Value::Number),
        }
    }
    fn array(&mut self, depth: usize) -> Option<Value> {
        self.offset += 1;
        self.space();
        let mut entries = Vec::new();
        if self.take(b']').is_some() {
            return Some(Value::Array(entries));
        }
        loop {
            entries.push(self.value(depth + 1)?);
            self.space();
            if self.take(b']').is_some() {
                break;
            }
            let comma = self.offset;
            if self.take(b',').is_none() {
                return self.fail("Expecting ',' delimiter", self.offset);
            }
            self.space();
            if self.peek() == Some(b']') && JsonDiagnostic::trailing(true) {
                return self.fail("Illegal trailing comma before end of array", comma);
            }
        }
        Some(Value::Array(entries))
    }
    fn object(&mut self, depth: usize) -> Option<Value> {
        self.offset += 1;
        self.space();
        let mut object = ManifestObject::new();
        if self.take(b'}').is_some() {
            return Some(Value::Object(object));
        }
        loop {
            self.space();
            if self.peek() != Some(b'"') {
                return self.fail(
                    "Expecting property name enclosed in double quotes",
                    self.offset,
                );
            }
            let key = self.string()?;
            self.space();
            if self.take(b':').is_none() {
                return self.fail("Expecting ':' delimiter", self.offset);
            }
            let value = self.value(depth + 1)?;
            object.insert(key, value);
            self.space();
            if self.take(b'}').is_some() {
                break;
            }
            let comma = self.offset;
            if self.take(b',').is_none() {
                return self.fail("Expecting ',' delimiter", self.offset);
            }
            self.space();
            if self.peek() == Some(b'}') && JsonDiagnostic::trailing(false) {
                return self.fail("Illegal trailing comma before end of object", comma);
            }
        }
        Some(Value::Object(object))
    }
}
#[cfg(test)]
#[path = "manifest_parser_diagnostic_tests.rs"]
mod diagnostic_tests;
#[cfg(test)]
#[path = "manifest_parser_tests.rs"]
mod tests;
