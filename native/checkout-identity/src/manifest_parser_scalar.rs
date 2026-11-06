//! owner: ManifestParser scalar methods; allowed imports: shared number/diagnostic,
//! serde_json string decoding; forbidden imports: alternate grammar/I/O;
//! callers/tests: ManifestParser; verification: lexical JSON and exact diagnostics.
use super::{diagnostic::JsonDiagnostic, ManifestParser};
use crate::python_json::Number;
impl ManifestParser<'_> {
    pub(super) fn string(&mut self) -> Option<String> {
        let start = self.offset;
        self.take(b'"')?;
        loop {
            match self.peek() {
                Some(b'"') => {
                    self.offset += 1;
                    let value = serde_json::from_str(&self.text[start..self.offset]).ok();
                    if value.is_none() {
                        self.unsupported = true;
                    }
                    return value;
                }
                Some(b'\\') => {
                    let slash = self.offset;
                    self.offset += 1;
                    match self.peek() {
                        Some(b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't') => {
                            self.offset += 1
                        }
                        Some(b'u') => {
                            let position = self.offset;
                            self.offset += 1;
                            if self.hex_unit().is_none() {
                                return self.fail("Invalid \\uXXXX escape", position);
                            }
                        }
                        None => return self.fail("Unterminated string starting at", start),
                        _ => return self.fail("Invalid \\escape", slash),
                    }
                }
                Some(0..=31) => return self.fail("Invalid control character at", self.offset),
                None => return self.fail("Unterminated string starting at", start),
                _ => self.offset += 1,
            }
        }
    }
    fn hex_unit(&mut self) -> Option<()> {
        for _ in 0..4 {
            if !self.peek()?.is_ascii_hexdigit() {
                return None;
            }
            self.offset += 1;
        }
        Some(())
    }
    pub(super) fn number(&mut self) -> Option<Number> {
        let start = self.offset;
        for special in ["NaN", "Infinity", "-Infinity"] {
            if self.literal(special).is_some() {
                return Number::from_token(special, self.digit_limit);
            }
        }
        if self.peek() == Some(b'-') {
            self.offset += 1;
        }
        match self.peek() {
            Some(b'0') => self.offset += 1,
            Some(b'1'..=b'9') => {
                while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                    self.offset += 1;
                }
            }
            _ => return self.fail("Expecting value", start),
        }
        if self.peek() == Some(b'.') {
            let dot = self.offset;
            self.offset += 1;
            let begin = self.offset;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.offset += 1;
            }
            if begin == self.offset {
                self.offset = dot;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            let exponent = self.offset;
            self.offset += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.offset += 1;
            }
            let begin = self.offset;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.offset += 1;
            }
            if begin == self.offset {
                self.offset = exponent;
            }
        }
        let token = &self.text[start..self.offset];
        let value = Number::from_token(token, self.digit_limit);
        if value.is_none() {
            if token.contains(['.', 'e', 'E']) {
                self.unsupported = true;
            } else {
                self.diagnostic =
                    JsonDiagnostic::digits(self.digit_limit, token.trim_start_matches('-').len());
            }
        }
        value
    }
}
