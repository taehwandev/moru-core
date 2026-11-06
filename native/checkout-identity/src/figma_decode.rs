//! owner: FigmaDecode; allowed imports: std UTF8 validation and shared newline normalization;
//! forbidden imports: IO/process/replacement decoding; callers/tests: FigmaProcess;
//! verification: Python TextIOWrapper read-all byte offsets, ranges and reasons.
use crate::text::Text;

pub(super) struct FigmaDecode;
impl FigmaDecode {
    pub(super) fn decode(bytes: &[u8]) -> Result<String, String> {
        match std::str::from_utf8(bytes) {
            Ok(text) => Ok(Text::universal_newlines(text)),
            Err(error) => {
                let start = error.valid_up_to();
                let count = error.error_len().unwrap_or(bytes.len() - start);
                let reason = if error.error_len().is_none() {
                    "unexpected end of data"
                } else if matches!(bytes[start], 0xc2..=0xf4) {
                    "invalid continuation byte"
                } else {
                    "invalid start byte"
                };
                let location = if count == 1 {
                    format!("byte 0x{:02x} in position {start}", bytes[start])
                } else {
                    format!("bytes in position {start}-{}", start + count - 1)
                };
                Err(format!("'utf-8' codec can't decode {location}: {reason}"))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn decoding_rejects_first_invalid_sequence_with_python_ranges() {
        for (bytes, message) in [
            (&b"\xff"[..], "byte 0xff in position 0: invalid start byte"),
            (&b"\x80"[..], "byte 0x80 in position 0: invalid start byte"),
            (
                &b"\xc0\x80"[..],
                "byte 0xc0 in position 0: invalid start byte",
            ),
            (
                &b"\xc2"[..],
                "byte 0xc2 in position 0: unexpected end of data",
            ),
            (
                &b"\xe2\x82A"[..],
                "bytes in position 0-1: invalid continuation byte",
            ),
            (
                &b"\xe2\x82"[..],
                "bytes in position 0-1: unexpected end of data",
            ),
            (
                &b"\xed\xa0\x80"[..],
                "byte 0xed in position 0: invalid continuation byte",
            ),
            (
                &b"\xf4\x90\x80\x80"[..],
                "byte 0xf4 in position 0: invalid continuation byte",
            ),
            (
                &b"a\r\n\xe2\x82A"[..],
                "bytes in position 3-4: invalid continuation byte",
            ),
        ] {
            assert_eq!(
                FigmaDecode::decode(bytes),
                Err(format!("'utf-8' codec can't decode {message}"))
            );
        }
    }

    #[test]
    fn read_all_keeps_offsets_across_buffers_and_preserves_bom() {
        let mut bytes = vec![b' '; 16385];
        bytes.extend_from_slice(b"\xf0\x9f\x92");
        assert_eq!(
            FigmaDecode::decode(&bytes),
            Err(
                "'utf-8' codec can't decode bytes in position 16385-16387: unexpected end of data"
                    .into()
            )
        );
        assert_eq!(
            FigmaDecode::decode(b"\xef\xbb\xbf[\r\n1,\r2\n]"),
            Ok("\u{feff}[\n1,\n2\n]".into())
        );
        assert_eq!(
            FigmaDecode::decode("한글\u{85}\r\n".as_bytes()),
            Ok("한글\u{85}\n".into())
        );
    }
}
