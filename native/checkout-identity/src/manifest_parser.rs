//! owner: ManifestParser; allowed imports: std, serde_json string decoder, manifest value modules;
//! forbidden imports: process/network; callers/tests: ReactManifest; verification: Python JSON fixtures.
use super::ParseOutcome;
use super::{number::ManifestNumber, object::ManifestObject, value::ManifestValue as Value};
pub(super) struct ManifestParser<'a> {
    text: &'a str,
    offset: usize,
    digit_limit: usize,
    unsupported: bool,
}
impl<'a> ManifestParser<'a> {
    pub fn parse(text: &'a str) -> Option<Value> {
        match Self::parse_outcome(text) {
            ParseOutcome::Value(value) => Some(value),
            _ => None,
        }
    }
    pub fn parse_outcome(text: &'a str) -> ParseOutcome {
        let digit_limit = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
            .unwrap_or("0")
            .parse()
            .ok();
        match digit_limit {
            Some(limit) => Self::outcome_with_limit(text, limit),
            None => ParseOutcome::Unsupported,
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
        let mut parser = Self {
            text,
            offset: 0,
            digit_limit,
            unsupported: false,
        };
        let value = parser.value(0);
        if parser.unsupported {
            return ParseOutcome::Unsupported;
        }
        parser.space();
        match value {
            Some(value) if parser.offset == text.len() => ParseOutcome::Value(value),
            _ => ParseOutcome::Invalid,
        }
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
        match self.peek()? {
            b'"' => self.string().map(Value::String),
            b'n' => {
                self.literal("null")?;
                Some(Value::Null)
            }
            b't' => {
                self.literal("true")?;
                Some(Value::Bool(true))
            }
            b'f' => {
                self.literal("false")?;
                Some(Value::Bool(false))
            }
            b'[' => {
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
                    self.take(b',')?;
                }
                Some(Value::Array(entries))
            }
            b'{' => {
                self.offset += 1;
                self.space();
                let mut object = ManifestObject::new();
                if self.take(b'}').is_some() {
                    return Some(Value::Object(object));
                }
                loop {
                    self.space();
                    let key = self.string()?;
                    self.space();
                    self.take(b':')?;
                    let value = self.value(depth + 1)?;
                    object.insert(key, value);
                    self.space();
                    if self.take(b'}').is_some() {
                        break;
                    }
                    self.take(b',')?;
                }
                Some(Value::Object(object))
            }
            _ => self.number().map(Value::Number),
        }
    }
    fn string(&mut self) -> Option<String> {
        let start = self.offset;
        self.take(b'"')?;
        loop {
            match self.peek()? {
                b'"' => {
                    self.offset += 1;
                    let value = serde_json::from_str(&self.text[start..self.offset]).ok();
                    if value.is_none() {
                        self.unsupported = true;
                    }
                    return value;
                }
                b'\\' => {
                    self.offset += 1;
                    match self.peek()? {
                        b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => self.offset += 1,
                        b'u' => {
                            self.offset += 1;
                            // Validate the complete string before decoding surrogate semantics.
                            self.hex_unit()?;
                        }
                        _ => return None,
                    }
                }
                0..=31 => return None,
                _ => self.offset += 1,
            }
        }
    }
    fn hex_unit(&mut self) -> Option<u16> {
        let mut unit = 0u16;
        for _ in 0..4 {
            let digit = match self.peek()? {
                b'0'..=b'9' => self.peek()? - b'0',
                b'a'..=b'f' => self.peek()? - b'a' + 10,
                b'A'..=b'F' => self.peek()? - b'A' + 10,
                _ => return None,
            };
            unit = unit * 16 + u16::from(digit);
            self.offset += 1;
        }
        Some(unit)
    }
    fn number(&mut self) -> Option<ManifestNumber> {
        let start = self.offset;
        for special in ["NaN", "Infinity", "-Infinity"] {
            if self.literal(special).is_some() {
                return ManifestNumber::from_token(special, self.digit_limit);
            }
        }
        if self.peek() == Some(b'-') {
            self.offset += 1;
        }
        match self.peek()? {
            b'0' => self.offset += 1,
            b'1'..=b'9' => {
                while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                    self.offset += 1;
                }
            }
            _ => return None,
        }
        if self.peek() == Some(b'.') {
            self.offset += 1;
            let begin = self.offset;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.offset += 1;
            }
            if begin == self.offset {
                return None;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.offset += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.offset += 1;
            }
            let begin = self.offset;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.offset += 1;
            }
            if begin == self.offset {
                return None;
            }
        }
        let token = &self.text[start..self.offset];
        let value = ManifestNumber::from_token(token, self.digit_limit);
        if value.is_none() && token.contains(['.', 'e', 'E']) {
            self.unsupported = true;
        }
        value
    }
}
#[cfg(test)]
#[path = "manifest_parser_tests.rs"]
mod tests;
