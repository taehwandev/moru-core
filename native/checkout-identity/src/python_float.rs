//! owner: PythonFloat; allowed imports: std, PythonText; forbidden imports: process/network;
//! callers/tests: Quota, overhead and subject tests; verification: Python float-string parity.
use crate::python_text::PythonText;
pub(crate) struct PythonFloat;
impl PythonFloat {
    pub(crate) fn parse(text: &str) -> Option<f64> {
        let mut normalized = String::with_capacity(text.len());
        for c in text.chars() {
            if c.is_ascii() {
                normalized.push(c);
            } else if let Some(digit) = PythonText::decimal_value(c) {
                normalized.push(char::from(b'0' + digit));
            } else if PythonText::whitespace(c) {
                normalized.push(' ');
            } else {
                return None;
            }
        }
        // float() keeps ASCII U+001C..U+001F unchanged; str.strip() does not.
        let text = normalized.trim_matches([' ', '\t', '\n', '\r', '\x0b', '\x0c']);
        let mut compact = String::with_capacity(text.len());
        let bytes = text.as_bytes();
        for (i, byte) in bytes.iter().enumerate() {
            if *byte == b'_' {
                if i == 0
                    || !bytes[i - 1].is_ascii_digit()
                    || !bytes.get(i + 1).is_some_and(u8::is_ascii_digit)
                {
                    return None;
                }
            } else {
                compact.push(char::from(*byte));
            }
        }
        let lower = compact.to_ascii_lowercase();
        let bare = lower.strip_prefix(['+', '-']).unwrap_or(&lower);
        match bare {
            "inf" | "infinity" => {
                return Some(if lower.starts_with('-') {
                    f64::NEG_INFINITY
                } else {
                    f64::INFINITY
                })
            }
            "nan" => {
                return Some(if lower.starts_with('-') {
                    -f64::NAN
                } else {
                    f64::NAN
                })
            }
            _ => {}
        }
        Self::valid(&compact)
            .then(|| compact.parse().ok())
            .flatten()
    }
    fn valid(text: &str) -> bool {
        let bytes = text.as_bytes();
        let mut at = 0;
        let digits = |at: &mut usize| {
            let start = *at;
            while bytes.get(*at).is_some_and(u8::is_ascii_digit) {
                *at += 1;
            }
            *at - start
        };
        if matches!(bytes.first(), Some(b'+' | b'-')) {
            at += 1;
        }
        let mut count = digits(&mut at);
        if bytes.get(at) == Some(&b'.') {
            at += 1;
            count += digits(&mut at);
        }
        if count == 0 {
            return false;
        }
        if matches!(bytes.get(at), Some(b'e' | b'E')) {
            at += 1;
            if matches!(bytes.get(at), Some(b'+' | b'-')) {
                at += 1;
            }
            if digits(&mut at) == 0 {
                return false;
            }
        }
        at == bytes.len()
    }
}
#[cfg(test)]
#[path = "python_float_tests.rs"]
mod tests;
