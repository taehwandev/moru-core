//! owner: Python class and block declaration starts and indentation for structural review.
//! allowed imports: shared Python whitespace rules and JSON input.
//! forbidden imports: filesystem, subprocesses and review outcomes.
//! callers/tests: native block spans, compared with the Python regex fallback.
//! verification: exact indentation and ASCII declarations with Unicode fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructurePythonBlocks;

impl StructurePythonBlocks {
    pub(super) fn top_level_classes(payload: &Value) -> Option<Value> {
        let lines = payload.get("lines")?.as_array()?;
        let unicode_matches =
            PythonText::matches_unicode_version(payload.get("unicode")?.as_str()?);
        let mut classes = Vec::new();
        for (index, line) in lines.iter().enumerate() {
            // The legacy owner rule only recognizes a literal class header at column zero.
            if let Some(tail) = Self::after_keyword(line.as_str()?, "class") {
                if let Some(name) = Self::identifier(tail, unicode_matches)? {
                    classes.push((index, name));
                }
            }
        }
        Some(json!({"classes": classes}))
    }

    pub(super) fn prepare(
        lines: &[Value],
        unicode_matches: bool,
    ) -> Option<(Vec<Option<i64>>, Vec<(usize, &str)>)> {
        let mut levels = Vec::with_capacity(lines.len());
        let mut starts = Vec::new();
        for (index, line) in lines.iter().enumerate() {
            let line = line.as_str()?;
            let stripped = Text::py_strip(line);
            let level = if stripped.is_empty() || stripped.starts_with(['#', '@']) {
                None
            } else {
                Some(i64::try_from(line.len() - line.trim_start_matches(' ').len()).ok()?)
            };
            levels.push(level);
            if let Some(name) = Self::name(stripped, unicode_matches)? {
                starts.push((index, name));
            }
        }
        Some((levels, starts))
    }

    fn name(line: &str, unicode_matches: bool) -> Option<Option<&str>> {
        let tail = Self::after_keyword(line, "def")
            .or_else(|| Self::after_keyword(line, "class"))
            .or_else(|| Self::after_keyword(Self::after_keyword(line, "async")?, "def"));
        let Some(tail) = tail else { return Some(None) };
        Self::identifier(tail, unicode_matches)
    }

    fn identifier(tail: &str, unicode_matches: bool) -> Option<Option<&str>> {
        if !tail
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return Some(None);
        }
        for (index, character) in tail.char_indices() {
            if !character.is_ascii() && !unicode_matches {
                return None;
            }
            if !PythonText::word(character) {
                return Some(tail.get(..index));
            }
        }
        Some(Some(tail))
    }

    fn after_keyword<'a>(line: &'a str, keyword: &str) -> Option<&'a str> {
        let suffix = line.strip_prefix(keyword)?;
        suffix
            .chars()
            .next()
            .filter(|character| Text::is_py_space(*character))
            .map(|_| suffix.trim_start_matches(Text::is_py_space))
    }
}
