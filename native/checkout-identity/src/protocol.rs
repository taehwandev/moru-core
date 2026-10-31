//! NDJSON framing and request handling for the checkout identity adapter.

use std::io::{self, BufRead, Write};

use serde_json::Value;

use crate::framing::Frame;
use crate::CheckoutIdentity;

const BOM: [u8; 3] = [0xEF, 0xBB, 0xBF];
const REPLACEMENT: &[u8] = b"\\uFFFD";

pub(crate) struct Protocol;

impl Protocol {
    pub(crate) fn serve<R: BufRead, W: Write>(mut reader: R, mut writer: W) -> io::Result<()> {
        let mut buf = Vec::new();
        loop {
            let reply = match Frame::read(&mut reader, &mut buf)? {
                Frame::Eof => return Ok(()),
                Frame::TooLarge => Self::failure("input_too_large"),
                Frame::Line => Self::respond(&buf),
            };
            writer.write_all(reply.as_bytes())?;
            writer.flush()?;
        }
    }

    fn respond(raw: &[u8]) -> String {
        let line = raw.strip_suffix(b"\n").unwrap_or(raw);
        let line = line.strip_prefix(&BOM).unwrap_or(line);
        let Ok(text) = std::str::from_utf8(line) else {
            return Self::failure("invalid_json");
        };
        let (scrubbed, lossy) = Self::scrub(text.as_bytes());
        let Ok(value) = serde_json::from_slice::<Value>(&scrubbed) else {
            return Self::failure("invalid_json");
        };
        let Some(root) = Self::root_of(&value) else {
            return Self::failure("invalid_request");
        };
        if lossy {
            return Self::failure("io_error");
        }
        match CheckoutIdentity::lookup(root) {
            Ok((common_dir, branch)) => Self::success(common_dir.as_deref(), &branch),
            Err(()) => Self::failure("io_error"),
        }
    }

    fn root_of(value: &Value) -> Option<&str> {
        let obj = value.as_object()?;
        if obj.len() != 2 || obj.get("schema_version")?.as_i64() != Some(1) {
            return None;
        }
        let root = obj.get("root")?.as_str()?;
        if root.is_empty() || !root.starts_with('/') || root.contains('\0') {
            return None;
        }
        Some(root)
    }

    /// Replace unpaired escaped UTF-16 surrogates inside JSON strings with
    /// `\uFFFD`. Returns the rewritten bytes and whether any replacement occurred.
    fn scrub(input: &[u8]) -> (Vec<u8>, bool) {
        let mut out = Vec::with_capacity(input.len());
        let mut in_str = false;
        let mut hit = false;
        let mut i = 0;
        while i < input.len() {
            let b = input[i];
            if !in_str {
                in_str = b == b'"';
                out.push(b);
                i += 1;
            } else if b == b'"' {
                in_str = false;
                out.push(b);
                i += 1;
            } else if b != b'\\' {
                out.push(b);
                i += 1;
            } else if let Some(unit) = Self::unit_at(input, i) {
                if (0xD800..0xDC00).contains(&unit) && Self::low_at(input, i + 6) {
                    out.extend_from_slice(&input[i..i + 12]);
                    i += 12;
                } else if (0xD800..0xE000).contains(&unit) {
                    out.extend_from_slice(REPLACEMENT);
                    hit = true;
                    i += 6;
                } else {
                    out.extend_from_slice(&input[i..i + 6]);
                    i += 6;
                }
            } else {
                let n = if i + 1 < input.len() { 2 } else { 1 };
                out.extend_from_slice(&input[i..i + n]);
                i += n;
            }
        }
        (out, hit)
    }

    /// Code unit of a well-formed `\uXXXX` escape starting at `at`.
    fn unit_at(input: &[u8], at: usize) -> Option<u16> {
        if input.get(at) != Some(&b'\\') || input.get(at + 1) != Some(&b'u') {
            return None;
        }
        let digits = input.get(at + 2..at + 6)?;
        let mut unit = 0u16;
        for &d in digits {
            unit = (unit << 4) | (d as char).to_digit(16)? as u16;
        }
        Some(unit)
    }

    fn low_at(input: &[u8], at: usize) -> bool {
        matches!(Self::unit_at(input, at), Some(0xDC00..=0xDFFF))
    }

    fn success(common_dir: Option<&str>, branch: &str) -> String {
        let common = match common_dir {
            Some(path) => Self::quote(path),
            None => "null".to_string(),
        };
        format!(
            "{{\"schema_version\":1,\"ok\":true,\"common_dir\":{common},\"branch\":{}}}\n",
            Self::quote(branch)
        )
    }

    fn failure(code: &str) -> String {
        format!("{{\"schema_version\":1,\"ok\":false,\"error\":\"{code}\"}}\n")
    }

    fn quote(text: &str) -> String {
        serde_json::to_string(text).unwrap_or_else(|_| "\"\"".to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn scrubs_lone_surrogate() {
        let (out, hit) = Protocol::scrub(br#"["\ud800x"]"#);
        assert_eq!(out, br#"["\uFFFDx"]"#.to_vec());
        assert!(hit);
    }

    #[test]
    fn keeps_valid_pair_and_escaped_backslash() {
        let pair = br#"["\ud83d\ude00"]"#;
        assert_eq!(Protocol::scrub(pair), (pair.to_vec(), false));
        let escaped = br#"["\\ud800"]"#;
        assert_eq!(Protocol::scrub(escaped), (escaped.to_vec(), false));
    }

    #[test]
    fn oversized_line_is_drained_then_reading_resumes() {
        let mut data = vec![b'a'; Frame::MAX_LINE + 10];
        data.extend_from_slice(b"\nx\n");
        let mut reader = Cursor::new(data);
        let mut buf = Vec::new();
        assert!(matches!(
            Frame::read(&mut reader, &mut buf),
            Ok(Frame::TooLarge)
        ));
        assert!(matches!(
            Frame::read(&mut reader, &mut buf),
            Ok(Frame::Line)
        ));
        assert_eq!(buf, b"x\n".to_vec());
    }

    #[test]
    fn rejects_bad_shapes() {
        assert!(
            Protocol::respond(b"{\"schema_version\":true,\"root\":\"/a\"}\n")
                .contains("invalid_request")
        );
        assert!(
            Protocol::respond(b"{\"schema_version\":1.0,\"root\":\"/a\"}\n")
                .contains("invalid_request")
        );
        assert!(
            Protocol::respond(b"{\"schema_version\":1,\"root\":\"a\"}\n")
                .contains("invalid_request")
        );
        assert!(Protocol::respond(b"nope\n").contains("invalid_json"));
    }
}
