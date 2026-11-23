//! owner: masked brace balance and selector starts for structure review.
//! allowed imports: existing whitespace rules and in-memory JSON lines.
//! forbidden imports: filesystem, Git execution, approval and mutation.
//! callers/tests: block span batch and Python regex parity fixtures.
//! verification: escaped quotations, comments, at-rules and line preservation.
use super::structure_code_blocks::StructureCodeBlocks;
use crate::text::Text;
use serde_json::Value;

pub(super) struct StructureStyleBlocks;

impl StructureStyleBlocks {
    pub(super) fn prepare(
        lines: &[Value],
        styles: bool,
        unicode_matches: bool,
    ) -> Option<(Vec<i64>, Vec<(usize, String)>)> {
        let source = lines
            .iter()
            .map(|value| value.as_str().filter(|line| !line.contains('\n')))
            .collect::<Option<Vec<_>>>()?;
        let joined = source.join("\n");
        let masked = Self::mask(&joined)?;
        let mut deltas = Vec::with_capacity(lines.len());
        let mut starts = Vec::new();
        for (index, (line, original)) in masked.split('\n').zip(source).enumerate() {
            let mut delta = 0i64;
            for character in line.bytes() {
                delta += i64::from(character == b'{') - i64::from(character == b'}');
            }
            deltas.push(delta);
            let line = Text::py_strip(line);
            if line.contains('{') {
                let start = if styles {
                    line.strip_suffix('{').is_some_and(|selector| {
                        !selector.is_empty()
                            && !selector.starts_with('@')
                            && !selector.contains(['{', '}'])
                    })
                } else {
                    StructureCodeBlocks::starts(line, unicode_matches)?
                };
                if start {
                    let label: String = Text::py_strip(original)
                        .chars()
                        .take(80)
                        .map(|character| if character == '`' { '\'' } else { character })
                        .collect();
                    starts.push((index, label));
                }
            }
        }
        Some((deltas, starts))
    }

    fn mask(text: &str) -> Option<String> {
        let bytes = text.as_bytes();
        let mut masked = bytes.to_vec();
        let mut index = 0;
        // Failed matches are retried one byte later, as in Python's regex.
        // Bound repeated lookahead and decline unusually expensive input.
        let mut budget = bytes.len().saturating_mul(8);
        while index < bytes.len() {
            let tail = &bytes[index..];
            let end = if tail.starts_with(b"//") {
                Some(
                    index
                        + tail
                            .iter()
                            .position(|byte| *byte == b'\n')
                            .unwrap_or(tail.len()),
                )
            } else if tail.starts_with(b"/*") {
                let body = &tail[2..];
                let length = body.windows(2).position(|pair| pair == b"*/");
                budget = budget.checked_sub(length.unwrap_or(body.len()))?;
                length.map(|length| index + length + 4)
            } else if matches!(bytes[index], b'\'' | b'"') {
                Self::quote_end(bytes, index, &mut budget)?
            } else {
                None
            };
            if let Some(end) = end {
                for byte in &mut masked[index..end] {
                    if *byte != b'\n' {
                        *byte = b' ';
                    }
                }
                index = end;
            } else {
                index += 1;
            }
        }
        String::from_utf8(masked).ok()
    }

    fn quote_end(bytes: &[u8], start: usize, budget: &mut usize) -> Option<Option<usize>> {
        let mut index = start + 1;
        while index < bytes.len() {
            *budget = budget.checked_sub(1)?;
            match bytes[index] {
                b'\n' => return Some(None),
                b'\\' => index += 2,
                byte if byte == bytes[start] => return Some(Some(index + 1)),
                _ => index += 1,
            }
        }
        Some(None)
    }
}
