//! owner: ordinary Kotlin top-level declaration headers and extension receivers.
//! allowed imports: Python-compatible text and JSON.
//! forbidden imports: filesystem, Git execution and owner decisions.
//! callers/tests: structural review through the completion probe and Python parity tests.
//! verification: modifiers, receiver order, nesting and fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureKotlinDeclarations;

struct Header<'a> {
    kind: &'a str,
    name: &'a str,
    receiver: Option<&'a str>,
    modifiers: String,
}

impl StructureKotlinDeclarations {
    pub(super) fn scan(input: &Value) -> Option<Value> {
        let unicode = PythonText::matches_unicode_version(input.get("unicode")?.as_str()?);
        let mut rows = Vec::new();
        let mut depth = 0usize;
        for (index, line) in input.get("lines")?.as_array()?.iter().enumerate() {
            let line = line.as_str()?;
            if !unicode && !line.is_ascii() {
                return None;
            }
            if depth == 0 {
                if let Some(header) = Self::header(Text::py_strip(line))? {
                    rows.push(json!([
                        index,
                        header.kind,
                        header.name,
                        header.modifiers,
                        header.receiver
                    ]));
                }
            }
            depth = (depth + line.bytes().filter(|&byte| byte == b'{').count())
                .saturating_sub(line.bytes().filter(|&byte| byte == b'}').count());
        }
        Some(json!({"declarations": rows}))
    }

    fn header(mut text: &str) -> Option<Option<Header<'_>>> {
        if text.is_empty()
            || text.starts_with(['*', '{', '}', ';'])
            || text.starts_with("//")
            || text.starts_with("/*")
        {
            return Some(None);
        }
        let mut modifiers = Vec::new();
        let mut type_only = false;
        let mut fun_only = false;
        let (kind, rest) = loop {
            if let Some(annotation) = text.strip_prefix('@') {
                text = Self::after_annotation(annotation)?;
                if text.is_empty() {
                    return Some(None);
                }
                continue;
            }
            let (token, next) = Self::split(text);
            match token {
                "public" | "private" | "protected" | "internal" | "open" | "final" | "expect"
                | "actual" | "inline" => {}
                "abstract" | "sealed" | "data" | "value" => type_only = true,
                "suspend" | "tailrec" | "operator" | "infix" | "external" => fun_only = true,
                _ => break (token, next),
            }
            modifiers.push(token);
            text = next;
        };
        if modifiers.is_empty() {
            if matches!(kind, "import" | "val") || kind == "var" && !rest.contains("=>") {
                return Some(None);
            }
            if kind == "package" {
                let (_, trailing) = Self::split(rest);
                return (trailing.is_empty()
                    || trailing.starts_with("//")
                    || trailing.starts_with("/*"))
                .then_some(None);
            }
        }
        let (kind, name, receiver) = match (kind, type_only, fun_only) {
            ("fun", false, _) => {
                let tail = if let Some(parameters) = rest.strip_prefix('<') {
                    let (parameters, tail) = parameters.split_once('>')?;
                    if parameters.is_empty() {
                        return None;
                    }
                    tail.trim_start_matches(Text::is_py_space)
                } else {
                    rest
                };
                let (name, receiver) = Self::function_name(tail)?;
                ("fun", name, receiver)
            }
            ("class" | "interface" | "object" | "typealias" | "enum" | "annotation", _, false) => {
                let (keyword, tail) = Self::split(rest);
                if matches!(kind, "enum" | "annotation") && keyword == "class" {
                    ("type", Self::name(tail)?, None)
                } else if kind != "annotation" {
                    (kind, Self::name(rest)?, None)
                } else {
                    return None;
                }
            }
            _ => return None,
        };
        Some(Some(Header {
            kind,
            name,
            receiver,
            modifiers: modifiers.join(" "),
        }))
    }

    fn after_annotation(text: &str) -> Option<&str> {
        let first = *text.as_bytes().first()?;
        if !first.is_ascii_alphabetic() && first != b'_' {
            return None;
        }
        let end = text
            .find(|ch: char| !ch.is_ascii_alphanumeric() && ch != '_' && ch != '.')
            .unwrap_or(text.len());
        let mut tail = &text[end..];
        if let Some(arguments) = tail.strip_prefix('(') {
            tail = arguments.split_once(')')?.1;
        }
        if tail.is_empty() || tail.chars().next().is_some_and(Text::is_py_space) {
            Some(tail.trim_start_matches(Text::is_py_space))
        } else {
            None
        }
    }

    fn function_name(text: &str) -> Option<(&str, Option<&str>)> {
        if !text
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return None;
        }
        let end = text
            .find(|ch: char| !ch.is_ascii_alphanumeric() && !"_?.<>".contains(ch))
            .unwrap_or(text.len());
        for (dot, _) in text[..end].rmatch_indices('.') {
            if let Some(name) = Self::name(&text[dot + 1..]) {
                return Some((name, Some(text[..dot].trim_end_matches('.'))));
            }
        }
        Some((Self::name(text)?, None))
    }

    fn name(text: &str) -> Option<&str> {
        if !text
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return None;
        }
        let end = text
            .find(|ch: char| !ch.is_ascii_alphanumeric() && ch != '_')
            .unwrap_or(text.len());
        (!text[end..].chars().next().is_some_and(PythonText::word)).then_some(&text[..end])
    }

    fn split(text: &str) -> (&str, &str) {
        let (word, rest) = text.split_once(Text::is_py_space).unwrap_or((text, ""));
        (word, rest.trim_start_matches(Text::is_py_space))
    }
}
