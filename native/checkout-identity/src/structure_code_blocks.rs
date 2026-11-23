//! owner: declaration matching for non-stylesheet braces in structure review.
//! allowed imports: shared Python-compatible whitespace.
//! forbidden imports: source IO, mutation and approval decisions.
//! callers/tests: shared brace masking and legacy declaration parity fixtures.
//! verification: declaration exclusions, prefixes and typed arrow functions.
use crate::text::Text;

pub(super) struct StructureCodeBlocks;

impl StructureCodeBlocks {
    pub(super) fn starts(line: &str) -> Option<bool> {
        // Python's regex word class includes Unicode categories that differ
        // across interpreters. Keep those candidates in the original matcher.
        if !line.is_ascii() {
            return None;
        }
        if Self::is_type(line) {
            return Some(false);
        }
        let (first, _) = Self::word(line);
        if matches!(
            first,
            "public"
                | "private"
                | "protected"
                | "internal"
                | "static"
                | "final"
                | "open"
                | "override"
                | "async"
                | "func"
                | "fun"
                | "def"
                | "fn"
                | "function"
                | "method"
                | "class"
                | "struct"
                | "enum"
                | "interface"
                | "type"
        ) {
            return Some(true);
        }
        let declaration = Self::after(line, "export").unwrap_or(line);
        let function = Self::after(declaration, "async").unwrap_or(declaration);
        if Self::after(function, "function").is_some_and(|tail| !Self::word(tail).0.is_empty()) {
            return Some(true);
        }
        Some(
            ["const", "let", "var"].into_iter().any(|keyword| {
                Self::after(declaration, keyword).is_some_and(Self::arrow_assignment)
            }),
        )
    }

    fn is_type(mut line: &str) -> bool {
        loop {
            let (first, rest) = Self::word(line);
            if matches!(
                first,
                "class"
                    | "struct"
                    | "enum"
                    | "interface"
                    | "object"
                    | "record"
                    | "actor"
                    | "protocol"
                    | "type"
            ) {
                return true;
            }
            if !matches!(
                first,
                "export"
                    | "default"
                    | "public"
                    | "private"
                    | "protected"
                    | "internal"
                    | "static"
                    | "final"
                    | "open"
                    | "abstract"
                    | "sealed"
                    | "data"
                    | "value"
                    | "annotation"
                    | "enum"
            ) {
                return false;
            }
            let next = rest.trim_start_matches(Text::is_py_space);
            if next.len() == rest.len() {
                return false;
            }
            line = next;
        }
    }

    fn arrow_assignment(line: &str) -> bool {
        let (name, rest) = Self::word(line);
        if name.is_empty() {
            return false;
        }
        let Some((annotation, expression)) = Text::py_strip(rest).split_once('=') else {
            return false;
        };
        if !Self::annotation(annotation) {
            return false;
        }
        let expression = expression.trim_start_matches(Text::is_py_space);
        Self::arrow(expression)
            || expression
                .strip_prefix("async")
                .is_some_and(|rest| Self::arrow(rest.trim_start_matches(Text::is_py_space)))
    }

    fn arrow(mut expression: &str) -> bool {
        if let Some(generic) = expression.strip_prefix('<') {
            let Some((parameters, rest)) = generic.split_once('>') else {
                return false;
            };
            if parameters.is_empty() || parameters.contains(['(', '{']) {
                return false;
            }
            expression = rest.trim_start_matches(Text::is_py_space);
        }
        let rest = if expression.starts_with('(') {
            let mut depth = 0;
            let mut closing = None;
            for (index, byte) in expression.bytes().enumerate() {
                if byte == b'(' {
                    depth += 1;
                    if depth > 2 {
                        return false;
                    }
                } else if byte == b')' {
                    depth -= 1;
                    if depth == 0 {
                        closing = Some(index + 1);
                        break;
                    }
                }
            }
            let Some(end) = closing else { return false };
            &expression[end..]
        } else {
            let (name, remainder) = Self::word(expression);
            if name.is_empty() {
                return false;
            }
            remainder
        };
        let Some((annotation, after_equals)) =
            rest.trim_start_matches(Text::is_py_space).split_once('=')
        else {
            return false;
        };
        Self::annotation(annotation) && after_equals.starts_with('>')
    }

    fn annotation(tail: &str) -> bool {
        tail.trim_matches(Text::is_py_space).is_empty()
            || tail
                .trim_start_matches(Text::is_py_space)
                .strip_prefix(':')
                .is_some_and(|annotation| !annotation.is_empty())
    }

    fn after<'a>(line: &'a str, keyword: &str) -> Option<&'a str> {
        let suffix = line.strip_prefix(keyword)?;
        let next = suffix.trim_start_matches(Text::is_py_space);
        (next.len() < suffix.len()).then_some(next)
    }

    fn word(line: &str) -> (&str, &str) {
        let length = line
            .bytes()
            .take_while(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
            .count();
        line.split_at(length)
    }
}
