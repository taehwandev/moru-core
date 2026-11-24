//! owner: top-level Swift and Dart declaration headers from the shared brace heuristic.
//! allowed imports: Python-compatible text and JSON.
//! forbidden imports: filesystem, Git and owner policy.
//! callers/tests: structural review completion probe and forced-Python parity.
//! verification: visibility, attributes, declaration order, raw braces and fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureBraceDeclarations;

impl StructureBraceDeclarations {
    pub(super) fn scan(input: &Value) -> Option<Value> {
        let unicode = PythonText::matches_unicode_version(input.get("unicode")?.as_str()?);
        let mut rows = Vec::new();
        let mut depth = 0usize;
        for (index, value) in input.get("lines")?.as_array()?.iter().enumerate() {
            let line = value.as_str()?;
            if depth == 0 {
                if !unicode && !line.is_ascii() {
                    return None;
                }
                if let Some((kind, name, modifiers)) = Self::declaration(Text::py_strip(line))? {
                    rows.push((index, kind, name, modifiers));
                }
            }
            // The reference counts raw braces even inside comments and strings.
            depth = (depth + line.bytes().filter(|&byte| byte == b'{').count())
                .saturating_sub(line.bytes().filter(|&byte| byte == b'}').count());
        }
        Some(json!({"declarations": rows}))
    }

    fn declaration(mut line: &str) -> Option<Option<(&str, &str, String)>> {
        if !Self::can_start_legacy_declaration(line) {
            return Some(None);
        }
        let mut modifiers = Vec::new();
        let mut type_only = false;
        let (mut kind, mut tail) = loop {
            if let Some(attribute) = line.strip_prefix('@') {
                line = Self::after_attribute(attribute)?;
                if line.is_empty() {
                    return Some(None);
                }
                continue;
            }
            if let Some(qualifier) = line.strip_prefix("nonisolated(") {
                let (argument, tail) = qualifier.split_once(')')?;
                if argument.contains('@') || !tail.chars().next().is_some_and(Text::is_py_space) {
                    return None;
                }
                modifiers.push(&line[..line.len() - tail.len()]);
                line = tail.trim_start_matches(Text::is_py_space);
                continue;
            }
            let (word, tail) = Self::split(line);
            match word {
                "public" | "private" | "fileprivate" | "protected" | "internal" | "package"
                | "open" | "final" | "static" | "nonisolated" | "pub" | "export" => {}
                "sealed" | "abstract" | "data" | "value" | "inline" | "indirect"
                | "distributed" | "readonly" | "expect" | "actual" => type_only = true,
                _ => break (word, tail),
            }
            modifiers.push(word);
            line = tail;
        };
        if kind == "async" && !type_only {
            // Legacy function metadata includes the async prefix.
            modifiers.push(kind);
            (kind, tail) = Self::split(tail);
            if !matches!(kind, "function" | "func" | "fun" | "fn") {
                return None;
            }
        }
        match kind {
            "enum" | "annotation" if Self::split(tail).0 == "class" => {
                kind = "type";
                tail = Self::split(tail).1;
            }
            "actor" | "class" | "enum" | "interface" | "object" | "protocol" | "record"
            | "struct" | "trait" | "type" | "typealias" => {}
            "function" | "func" | "fun" | "fn" if !type_only => {}
            "const" | "let" | "var" if !tail.contains("=>") => return Some(None),
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
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
            || tail[end..].chars().next().is_some_and(PythonText::word)
        {
            return None;
        }
        Some(Some((kind, name, modifiers.join(" "))))
    }

    fn after_attribute(attribute: &str) -> Option<&str> {
        if !attribute
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return None;
        }
        let end = attribute
            .bytes()
            .take_while(|byte| byte.is_ascii_alphanumeric() || *byte == b'_' || *byte == b'.')
            .count();
        let mut tail = &attribute[end..];
        if let Some(args) = tail.strip_prefix('(') {
            tail = args.split_once(')')?.1;
        }
        (tail.is_empty() || tail.chars().next().is_some_and(Text::is_py_space))
            .then(|| tail.trim_start_matches(Text::is_py_space))
    }

    pub(super) fn can_start_legacy_declaration(line: &str) -> bool {
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

    fn split(line: &str) -> (&str, &str) {
        let (first, tail) = line.split_once(Text::is_py_space).unwrap_or((line, ""));
        (first, tail.trim_start_matches(Text::is_py_space))
    }
}
