//! owner: ordinary JavaScript and TypeScript declaration headers for structural review.
//! allowed imports: Python-compatible text and JSON.
//! forbidden imports: filesystem, Git execution and owner policy.
//! callers/tests: JavaScript completion probe, native TypeScript text processing and parity fixtures.
//! verification: header precedence, nesting and unsupported syntax fallback.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureJsDeclarations;

impl StructureJsDeclarations {
    pub(super) fn request(input: &Value) -> Option<Value> {
        let lines = input
            .get("lines")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"declarations": Self::scan(&lines, input.get("unicode")?.as_str()?, false)?}))
    }

    pub(super) fn scan(
        lines: &[&str],
        unicode_version: &str,
        typescript: bool,
    ) -> Option<Vec<Value>> {
        if !PythonText::matches_unicode_version(unicode_version)
            && lines.iter().any(|line| !line.is_ascii())
        {
            return None;
        }
        let mut matches = Vec::new();
        let mut depth = 0usize;
        for (index, line) in lines.iter().enumerate() {
            if depth == 0 {
                if let Some((kind, name, modifiers)) = Self::header(line, typescript)? {
                    matches.push(json!([index, kind, name, modifiers]));
                }
            }
            depth = (depth + line.bytes().filter(|&byte| byte == b'{').count())
                .saturating_sub(line.bytes().filter(|&byte| byte == b'}').count());
        }
        Some(matches)
    }

    fn header(line: &str, typescript: bool) -> Option<Option<(&str, &str, &str)>> {
        let mut tail = line.trim_start_matches(Text::is_py_space);
        if tail.is_empty()
            || tail.starts_with(['*', '{', '}', ';'])
            || tail.starts_with("//")
            || tail.starts_with("/*")
        {
            return Some(None);
        }
        let exported = Self::after(tail, "export");
        if let Some(rest) = exported {
            tail = rest;
            if tail.starts_with(['{', '*']) {
                return Some(None);
            }
            let (kind, name_tail) = Self::split(tail);
            if matches!(kind, "const" | "let" | "var") {
                let prefix = &line[..line.len() - tail.len()];
                if typescript {
                    return Some(Self::name(name_tail, true).map(|(name, _)| (kind, name, prefix)));
                }
                let name = Self::name(name_tail, false).filter(|(_, rest)| Self::arrow(rest));
                return Some(name.map(|(name, _)| ("type", name, prefix)));
            }
            tail = Self::after(tail, "default").unwrap_or(tail);
        }
        let abstract_tail = Self::after(tail, "abstract");
        if let Some(rest) = abstract_tail {
            tail = rest;
        }
        let (kind, name_tail) = Self::split(tail);
        if matches!(kind, "class" | "interface" | "enum" | "type") {
            if kind == "enum" && Self::after(name_tail, "class").is_some() {
                return None;
            }
            let prefix = &line[..line.len() - tail.len()];
            return Some(Self::name(name_tail, false).map(|(name, _)| (kind, name, prefix)));
        }
        if abstract_tail.is_some() {
            return None;
        }
        let function = Self::after(tail, "async").unwrap_or(tail);
        let (kind, name_tail) = Self::split(function);
        if matches!(kind, "function" | "func" | "fun" | "fn") {
            let prefix = &line[..line.len() - function.len()];
            return Some(Self::name(name_tail, false).map(|(name, _)| (kind, name, prefix)));
        }
        if exported.is_none() && tail == function && matches!(kind, "const" | "let" | "var") {
            let name = Self::name(name_tail, false).filter(|(_, rest)| Self::arrow(rest));
            return Some(name.map(|(name, _)| ("type", name, "")));
        }
        if exported.is_none() && kind == "import" {
            return Some(None);
        }
        None
    }

    fn name(text: &str, unicode_tail: bool) -> Option<(&str, &str)> {
        if !text
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return None;
        }
        let end = text
            .find(|ch: char| {
                if unicode_tail {
                    !PythonText::word(ch)
                } else {
                    !ch.is_ascii_alphanumeric() && ch != '_'
                }
            })
            .unwrap_or(text.len());
        let (name, rest) = text.split_at(end);
        if rest.chars().next().is_some_and(PythonText::word) {
            return None;
        }
        Some((name, rest))
    }

    fn arrow(rest: &str) -> bool {
        let Some(args) = rest.trim_start_matches(Text::is_py_space).strip_prefix('=') else {
            return false;
        };
        let args = args.trim_start_matches(Text::is_py_space);
        let tail = |args: &str| {
            let end = if args.starts_with('(') {
                args.find(')').map(|index| &args[index + 1..])
            } else {
                Self::name(args, false).map(|(_, rest)| rest)
            };
            end.is_some_and(|rest| rest.trim_start_matches(Text::is_py_space).starts_with("=>"))
        };
        args.strip_prefix("async")
            .is_some_and(|rest| tail(rest.trim_start_matches(Text::is_py_space)))
            || tail(args)
    }

    fn after<'a>(text: &'a str, key: &str) -> Option<&'a str> {
        let tail = text.strip_prefix(key)?;
        tail.chars().next().filter(|&ch| Text::is_py_space(ch))?;
        Some(tail.trim_start_matches(Text::is_py_space))
    }

    fn split(text: &str) -> (&str, &str) {
        let (key, rest) = text.split_once(Text::is_py_space).unwrap_or((text, ""));
        (key, rest.trim_start_matches(Text::is_py_space))
    }
}
