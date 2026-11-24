//! owner: ordinary Go top-level declaration recognition for structural review.
//! allowed imports: Python-compatible text predicates and JSON.
//! forbidden imports: filesystem, Git execution and owner policy.
//! callers/tests: structural review completion probe and forced-Python parity.
//! verification: declaration order, brace depth, and whole-file fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureGoDeclarations;

impl StructureGoDeclarations {
    pub(super) fn scan(input: &Value) -> Option<Value> {
        let unicode_matches = PythonText::matches_unicode_version(input.get("unicode")?.as_str()?);
        let mut rows = Vec::new();
        let mut depth = 0usize;
        for (index, line) in input.get("lines")?.as_array()?.iter().enumerate() {
            let line = line.as_str()?;
            let stripped = Text::py_strip(line);
            if depth == 0 {
                if let Some((kind, name)) = Self::declaration(stripped, unicode_matches)? {
                    rows.push((index, kind, name));
                }
            }
            // Match the legacy heuristic, which counts literal braces even in comments.
            depth = (depth + line.bytes().filter(|&byte| byte == b'{').count())
                .saturating_sub(line.bytes().filter(|&byte| byte == b'}').count());
        }
        Some(json!({"declarations": rows}))
    }

    fn declaration(line: &str, unicode_matches: bool) -> Option<Option<(&'static str, &str)>> {
        if line.is_empty()
            || line.starts_with("//")
            || line.starts_with("/*")
            || line.starts_with(['*', ')', '}'])
        {
            return Some(None);
        }
        let (keyword, rest) = line.split_once(Text::is_py_space).unwrap_or((line, ""));
        let rest = rest.trim_start_matches(Text::is_py_space);
        match keyword {
            "type" => Some(Self::name(rest, unicode_matches)?.map(|name| ("type", name))),
            "func" => Some(Self::name(rest, unicode_matches)?.map(|name| ("func", name))),
            "import" => Some(None),
            "var" | "const" if !rest.contains("=>") => Some(None),
            "package" => {
                let tail = rest.find(Text::is_py_space).map_or("", |index| {
                    rest[index..].trim_start_matches(Text::is_py_space)
                });
                (tail.is_empty() || tail.starts_with("//") || tail.starts_with("/*"))
                    .then_some(None)
            }
            _ => None,
        }
    }

    fn name(rest: &str, unicode_matches: bool) -> Option<Option<&str>> {
        if !rest
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return Some(None);
        }
        let end = rest
            .bytes()
            .take_while(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
            .count();
        if let Some(next) = rest[end..].chars().next() {
            if !next.is_ascii() && !unicode_matches {
                return None;
            }
            if PythonText::word(next) {
                return Some(None);
            }
        }
        Some(Some(&rest[..end]))
    }
}
