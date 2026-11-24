//! owner: ordinary Rust top-level declaration headers for structural review.
//! allowed imports: Python-compatible text predicates and JSON.
//! forbidden imports: filesystem, Git, and ownership policy.
//! callers/tests: completion probe and forced-Python structural review parity.
//! verification: visibility prefixes, source order, raw braces, and fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureRustDeclarations;

impl StructureRustDeclarations {
    pub(super) fn scan(input: &Value) -> Option<Value> {
        let unicode = PythonText::matches_unicode_version(input.get("unicode")?.as_str()?);
        let mut depth = 0usize;
        let mut rows = Vec::new();
        for (index, line) in input.get("lines")?.as_array()?.iter().enumerate() {
            let line = line.as_str()?;
            if depth == 0 {
                if !unicode && !line.is_ascii() {
                    return None;
                }
                if let Some((kind, name, modifiers)) = Self::declaration(Text::py_strip(line))? {
                    rows.push((index, kind, name, modifiers));
                }
            }
            // Review counts braces in raw text, including inside strings and comments.
            depth = (depth + line.bytes().filter(|&byte| byte == b'{').count())
                .saturating_sub(line.bytes().filter(|&byte| byte == b'}').count());
        }
        Some(json!({"declarations": rows}))
    }

    fn declaration(line: &str) -> Option<Option<(&str, &str, &'static str)>> {
        if !Self::can_start_legacy_declaration(line) {
            return Some(None);
        }
        let (line, modifiers) = Self::visibility(line)?;
        let (mut kind, mut tail) = Self::split(line);
        if kind == "async" {
            (kind, tail) = Self::split(tail);
            if kind != "fn" {
                return None;
            }
        }
        match kind {
            "struct" | "enum" | "trait" | "type" | "fn" => {}
            "impl" | "mod" | "use" | "union" | "unsafe" | "extern" | "macro_rules!" => {
                return Some(None);
            }
            "const" | "let" | "var" if !tail.contains("=>") => return Some(None),
            "static" if Self::split(tail).0 == "mut" || Self::static_value(tail) => {
                return Some(None);
            }
            _ => return None,
        }
        let end = tail
            .bytes()
            .take_while(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
            .count();
        let name = &tail[..end];
        if !name
            .as_bytes()
            .first()
            .is_some_and(|byte| Self::name_start(*byte))
            || tail[end..].starts_with('#')
            || tail[end..].chars().next().is_some_and(PythonText::word)
        {
            return None;
        }
        Some(Some((kind, name, modifiers)))
    }

    fn can_start_legacy_declaration(line: &str) -> bool {
        // The reference expressions are line-anchored and require whitespace
        // after the first keyword or modifier. A tuple, continuation, generic
        // impl, or macro call cannot match unless it starts with one of these
        // prefixes. Keep legacy-only prefixes eligible for fallback.
        let (first, _) = Self::split(line);
        line.starts_with('@')
            || line.starts_with("pub(")
            || line.starts_with("nonisolated(")
            || matches!(
                first,
                "export"
                    | "public"
                    | "package"
                    | "private"
                    | "fileprivate"
                    | "protected"
                    | "internal"
                    | "open"
                    | "final"
                    | "sealed"
                    | "abstract"
                    | "data"
                    | "value"
                    | "inline"
                    | "indirect"
                    | "nonisolated"
                    | "distributed"
                    | "static"
                    | "readonly"
                    | "expect"
                    | "actual"
                    | "pub"
                    | "enum"
                    | "annotation"
                    | "class"
                    | "interface"
                    | "struct"
                    | "record"
                    | "object"
                    | "protocol"
                    | "actor"
                    | "typealias"
                    | "type"
                    | "trait"
                    | "async"
                    | "function"
                    | "func"
                    | "fun"
                    | "fn"
                    | "const"
                    | "let"
                    | "var"
            )
    }

    fn visibility(line: &str) -> Option<(&str, &'static str)> {
        if let Some(rest) = line.strip_prefix("pub(") {
            let (scope, tail) = rest.split_once(')')?;
            let (head, path) = Self::split(scope);
            let valid_path = path
                .as_bytes()
                .first()
                .is_some_and(|byte| Self::name_start(*byte))
                && path
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_:".contains(&byte));
            if !matches!(scope, "crate" | "super" | "self") && !(head == "in" && valid_path) {
                return None;
            }
            return tail
                .chars()
                .next()
                .filter(|ch| Text::is_py_space(*ch))
                .map(|_| (tail.trim_start_matches(Text::is_py_space), "pub"));
        }
        let (word, tail) = Self::split(line);
        if word == "pub" {
            Some((tail, "pub"))
        } else {
            Some((line, ""))
        }
    }

    fn name_start(byte: u8) -> bool {
        byte.is_ascii_alphabetic() || byte == b'_'
    }

    fn static_value(tail: &str) -> bool {
        tail.split_once(':').is_some_and(|(name, _)| {
            let name = name.trim_end_matches(Text::is_py_space);
            !name.is_empty()
                && name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
        })
    }

    fn split(text: &str) -> (&str, &str) {
        let (word, rest) = text.split_once(Text::is_py_space).unwrap_or((text, ""));
        (word, rest.trim_start_matches(Text::is_py_space))
    }
}
