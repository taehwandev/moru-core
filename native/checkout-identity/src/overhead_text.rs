//! owner: OverheadText; allowed imports: Python JSON/text, private pattern matcher;
//! forbidden imports: IO, logging raw prompts or commands; callers/tests: OverheadHooks;
//! verification: reference redaction and guidance path matching.
#[path = "overhead_text_patterns.rs"]
mod patterns;
use crate::{
    python_json::{PythonJson as Py, Value},
    python_text::PythonText,
};
pub(crate) struct OverheadText;
impl OverheadText {
    pub(crate) fn text(value: &Value) -> String {
        match value {
            Value::String(s) => s.clone(),
            Value::Array(items) => items
                .iter()
                .map(|item| {
                    if item.is_object() {
                        Self::text(item.get("text").unwrap_or(&item["content"]))
                    } else {
                        Py::string(item)
                    }
                })
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
                .join("\n"),
            Value::Null => String::new(),
            _ => Py::string(value),
        }
    }
    pub(crate) fn normalize(text: &str) -> Option<String> {
        let joined = text
            .split(PythonText::whitespace)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" ")
            .replace("Tao Agent OS", "Moru Core")
            .replace("Tao ", "Moru ");
        let chars: Vec<char> = joined.chars().collect();
        let mut redacted = String::new();
        let mut i = 0;
        while i < chars.len() {
            let starts = |s: &str| chars[i..].iter().copied().take(s.len()).eq(s.chars());
            let prefix = [
                "/private/Users",
                "/private/home",
                "/private/tmp",
                "/private/var",
                "/private/private",
                "/Users",
                "/home",
                "/tmp",
                "/var",
                "/private",
            ]
            .iter()
            .find(|s| starts(s));
            if prefix.is_some() {
                while i < chars.len()
                    && !PythonText::whitespace(chars[i])
                    && !"`'\",;)]".contains(chars[i])
                {
                    i += 1;
                }
                redacted.push_str("<path>");
            } else {
                redacted.push(chars[i]);
                i += 1;
            }
        }
        let chars: Vec<char> = redacted.chars().collect();
        let mut ids = String::new();
        let mut i = 0;
        while i < chars.len() {
            if chars[i].is_ascii_digit() || ('a'..='f').contains(&chars[i]) {
                let start = i;
                while i < chars.len()
                    && (chars[i].is_ascii_digit() || ('a'..='f').contains(&chars[i]))
                {
                    i += 1;
                }
                if i - start >= 16
                    && !patterns::Patterns::word_before(&chars, start)?
                    && !patterns::Patterns::word_after(&chars, i)?
                {
                    ids.push_str("<id>");
                } else {
                    ids.extend(&chars[start..i]);
                }
            } else {
                ids.push(chars[i]);
                i += 1;
            }
        }
        let chars: Vec<char> = ids.chars().collect();
        let mut output = String::new();
        let mut i = 0;
        while i < chars.len() {
            if chars[i..].iter().copied().take(6).eq("toolu_".chars()) {
                let mut end = i + 6;
                while end < chars.len() && patterns::Patterns::word(chars[end])? {
                    end += 1;
                }
                if end > i + 6 {
                    output.push_str("<toolu>");
                    i = end;
                    continue;
                }
            }
            output.push(chars[i]);
            i += 1;
        }
        Some(output.chars().take(120).collect())
    }
    pub(crate) fn guidance(path: &Value, roots: &[String]) -> bool {
        let Some(path) = path.as_str() else {
            return false;
        };
        for base in roots {
            for root in [base.clone(), format!("{base}-worktrees")] {
                let Some(mut relative) = path.strip_prefix(&format!("{root}/")) else {
                    continue;
                };
                if root.ends_with("-worktrees") {
                    relative = relative.split_once('/').map_or("", |(_, rest)| rest);
                }
                for prefix in [".moru/worktrees/", ".claude/worktrees/"] {
                    if let Some(tail) = relative.strip_prefix(prefix) {
                        if let Some((name, rest)) = tail.split_once('/') {
                            let rest = rest.strip_suffix('\n').unwrap_or(rest);
                            if !name.is_empty() && !rest.contains('\n') {
                                relative = rest;
                            }
                        }
                        break;
                    }
                }
                return matches!(
                    relative.split('/').next(),
                    Some(
                        "common"
                            | "workflows"
                            | "docs"
                            | "platforms"
                            | "AGENTS.md"
                            | "CLAUDE.md"
                            | "index.md"
                            | "README.md"
                    )
                );
            }
        }
        false
    }
    pub(crate) fn launcher(text: &str, known: bool) -> Option<Option<String>> {
        patterns::Patterns::launcher(text, known)
    }
    pub(crate) fn mark(text: &str) -> Option<bool> {
        patterns::Patterns::mark(text)
    }
    pub(crate) fn note(text: &str) -> bool {
        patterns::Patterns::note(text)
    }
    pub(crate) fn search(text: &str) -> Option<bool> {
        patterns::Patterns::search(text)
    }
    pub(crate) fn bash_guidance(text: &str) -> Option<bool> {
        patterns::Patterns::guidance(text)
    }
    pub(crate) fn denial(text: &str) -> Option<&str> {
        patterns::Patterns::denial(text)
    }
    pub(crate) fn launcher_mark(text: &str) -> bool {
        ["moru-hook", "tao-hook", "agent-hook"]
            .iter()
            .any(|name| text.contains(name))
    }
}

#[cfg(test)]
#[path = "overhead_text_tests.rs"]
mod tests;
