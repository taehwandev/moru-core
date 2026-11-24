//! owner: TypeScript structural masking and declaration reference text.
//! allowed imports: Python text compatibility, local collections and JSON.
//! forbidden imports: filesystem, Git execution and owner policy.
//! callers/tests: structural declaration review and Python parity fixtures.
//! verification: masking precedence, line boundaries and reference ranges.
use super::structure_js_declarations::StructureJsDeclarations;
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub(super) struct StructureTsText;

impl StructureTsText {
    pub(super) fn process(input: &Value) -> Option<Value> {
        let lines = input
            .get("lines")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        match input.get("mode")?.as_str()? {
            "mask" => {
                let masked = Self::mask(&lines.join("\n"))?;
                Some(json!({"lines": PythonText::splitlines(&masked)}))
            }
            "declarations" => {
                let masked = Self::mask(&lines.join("\n"))?;
                let lines = PythonText::splitlines(&masked);
                let matches =
                    StructureJsDeclarations::scan(&lines, input.get("unicode")?.as_str()?, true);
                Some(json!({"lines": lines, "declarations": matches}))
            }
            "references" => Self::references(input, &lines),
            _ => None,
        }
    }

    fn mask(source: &str) -> Option<String> {
        let bytes = source.as_bytes();
        let mut budget = bytes.len().saturating_mul(8);
        let mut result = String::with_capacity(bytes.len());
        let mut cursor = 0;
        let mut copied = 0;
        while cursor < bytes.len() {
            let Some(end) = Self::masked_end(bytes, cursor, &mut budget)? else {
                cursor += 1;
                continue;
            };
            result.push_str(&source[copied..cursor]);
            for _ in bytes[cursor..end].iter().filter(|&&byte| byte == b'\n') {
                result.push('\n');
            }
            copied = end;
            cursor = end;
        }
        result.push_str(&source[copied..]);
        Some(result)
    }

    fn masked_end(bytes: &[u8], start: usize, budget: &mut usize) -> Option<Option<usize>> {
        if start > 0 && matches!(bytes[start - 1], b'=' | b'>') {
            let slash = start
                + bytes[start..]
                    .iter()
                    .take_while(|&&byte| matches!(byte, b' ' | b'\t'))
                    .count();
            if bytes.get(slash) == Some(&b'/') && !matches!(bytes.get(slash + 1), Some(b'/' | b'*'))
            {
                if let Some(end) = Self::quoted_end(bytes, slash, b'/', budget)? {
                    let flags = bytes[end..]
                        .iter()
                        .take_while(|byte| byte.is_ascii_lowercase())
                        .count();
                    return Some(Some(end + flags));
                }
            }
        }
        match bytes[start] {
            b'/' if bytes.get(start + 1) == Some(&b'/') => {
                let end = bytes[start..].iter().position(|&byte| byte == b'\n');
                Some(Some(end.map_or(bytes.len(), |offset| start + offset)))
            }
            b'/' if bytes.get(start + 1) == Some(&b'*') => {
                for (offset, pair) in bytes[start + 2..].windows(2).enumerate() {
                    *budget = budget.checked_sub(1)?;
                    if pair == b"*/" {
                        return Some(Some(start + offset + 4));
                    }
                }
                Some(None)
            }
            quote @ (b'\'' | b'"' | b'\x60') => Self::quoted_end(bytes, start, quote, budget),
            _ => Some(None),
        }
    }

    fn quoted_end(
        bytes: &[u8],
        start: usize,
        quote: u8,
        budget: &mut usize,
    ) -> Option<Option<usize>> {
        let mut cursor = start + 1;
        let regex = quote == b'/';
        while let Some(&byte) = bytes.get(cursor) {
            *budget = budget.checked_sub(1)?;
            if byte == quote {
                return Some((!regex || cursor > start + 1).then_some(cursor + 1));
            }
            if regex && byte == b'\n' {
                break;
            }
            if byte == b'\\' {
                cursor += 1;
                if matches!(bytes.get(cursor), None | Some(b'\n')) {
                    break;
                }
            }
            cursor += 1;
        }
        Some(None)
    }

    fn references(input: &Value, lines: &[&str]) -> Option<Value> {
        if !PythonText::matches_unicode_version(input.get("unicode")?.as_str()?)
            && lines.iter().any(|line| !line.is_ascii())
        {
            return None;
        }
        let mut prior = 0;
        let mut owners = Vec::new();
        for entry in input.get("owners")?.as_array()? {
            let line = usize::try_from(entry.get(0)?.as_u64()?).ok()?;
            if line <= prior || line > lines.len() {
                return None;
            }
            prior = line;
            owners.push((line, entry.get(1)?.as_str()?));
        }
        let mut references = Vec::with_capacity(owners.len());
        for (index, &(start, name)) in owners.iter().enumerate() {
            let end = owners
                .get(index + 1)
                .map_or(lines.len(), |(line, _)| line - 1);
            let names: BTreeSet<_> = lines[start - 1..end]
                .iter()
                .flat_map(|line| line.split(|ch| !PythonText::word(ch)))
                .filter(|word| {
                    *word != name
                        && word
                            .as_bytes()
                            .first()
                            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
                })
                .collect();
            references.push(names);
        }
        Some(json!({"references": references}))
    }
}
