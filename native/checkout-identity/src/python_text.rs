//! owner: PythonText; allowed imports: std, serde JSON and generated Unicode tables;
//! forbidden imports: runtime Python/process/network; callers/tests: manifest validators,
//! CLI adapters and subject tests; verification: exhaustive scalar golden digest.
use std::fmt::Write;
#[path = "python_utf8.rs"]
mod utf8;
pub(crate) use utf8::PythonUtf8;
include!(concat!(env!("OUT_DIR"), "/python_text_contract.rs"));

pub(crate) struct PythonText;
impl PythonText {
    pub(crate) fn json_ascii(text: &str) -> Option<String> {
        let escaped = serde_json::to_string(text).ok()?;
        Some(Self::escape_json_unicode(&escaped))
    }

    pub(crate) fn escape_json_unicode(escaped: &str) -> String {
        let mut result = String::new();
        for character in escaped.chars() {
            if character >= '\u{7f}' {
                for unit in character.encode_utf16(&mut [0; 2]) {
                    write!(result, "\\u{unit:04x}").unwrap();
                }
            } else {
                result.push(character);
            }
        }
        result
    }

    pub(crate) fn matches_unicode_version(version: &str) -> bool {
        version == UNICODE_VERSION
    }

    pub(crate) fn repr(value: &str) -> String {
        let quote = if value.contains('\'') && !value.contains('"') {
            '"'
        } else {
            '\''
        };
        let mut output = String::with_capacity(value.len() + 2);
        output.push(quote);
        for character in value.chars() {
            match character {
                '\\' => output.push_str("\\\\"),
                '\t' => output.push_str("\\t"),
                '\n' => output.push_str("\\n"),
                '\r' => output.push_str("\\r"),
                c if c == quote => {
                    output.push('\\');
                    output.push(c);
                }
                c if Self::printable(c) => output.push(c),
                c => {
                    let codepoint = c as u32;
                    if codepoint <= 0xff {
                        write!(output, "\\x{codepoint:02x}").unwrap();
                    } else if codepoint <= 0xffff {
                        write!(output, "\\u{codepoint:04x}").unwrap();
                    } else {
                        write!(output, "\\U{codepoint:08x}").unwrap();
                    }
                }
            }
        }
        output.push(quote);
        output
    }
    pub(crate) fn decimal(character: char) -> bool {
        Self::contains(DECIMAL, character)
    }
    pub(crate) fn decimal_value(character: char) -> Option<u8> {
        let cp = character as u32;
        let index = DECIMAL.partition_point(|(_, end)| *end < cp);
        let (start, _) = DECIMAL.get(index)?;
        (cp >= *start).then(|| ((cp - start) % 10) as u8)
    }
    pub(crate) fn whitespace(character: char) -> bool {
        Self::contains(WHITESPACE, character)
    }
    pub(crate) fn printable(character: char) -> bool {
        Self::contains(PRINTABLE, character)
    }
    fn contains(ranges: &[(u32, u32)], character: char) -> bool {
        let codepoint = character as u32;
        let index = ranges.partition_point(|(_, end)| *end < codepoint);
        ranges
            .get(index)
            .is_some_and(|(start, _)| *start <= codepoint)
    }
}
#[cfg(test)]
#[path = "python_text_tests.rs"]
mod tests;
