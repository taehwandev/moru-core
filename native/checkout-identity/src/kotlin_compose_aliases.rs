//! owner: ordered import alias expansion for Compose structural review.
//! allowed imports: shared Python text classes and standard-library strings.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Kotlin mask probe and exact legacy alias comparison.
//! verification: original import snapshot, ordered replacements and word boundaries.
use crate::python_text::PythonText;
use std::borrow::Cow;

pub(super) struct KotlinComposeAliases;

impl KotlinComposeAliases {
    pub(super) fn normalize<'a>(code: &'a str, unicode: &str) -> Option<Cow<'a, str>> {
        if !PythonText::matches_unicode_version(unicode) && !code.is_ascii() {
            return None;
        }
        let mut normalized = Cow::Borrowed(code);
        let mut consumed = 0;
        let mut budget = 4_000_000usize;
        // Discover aliases from the original mask and apply them to the evolving code.
        for (index, _) in code.match_indices("import") {
            if index < consumed {
                continue;
            }
            let Some((original, alias, end)) = Self::import(&code[index + "import".len()..]) else {
                continue;
            };
            consumed = code.len() - end.len();
            let (needle, replacement, leading_word_boundary) =
                if original == "androidx.compose.runtime.Composable" {
                    (Cow::Owned(format!("@{alias}")), "@Composable", false)
                } else if original.split('.').any(|part| {
                    ["RouteEvent", "NavigationEvent", "NoticeEffect"]
                        .iter()
                        .any(|suffix| part.ends_with(suffix))
                }) {
                    (Cow::Borrowed(alias), original, true)
                } else {
                    continue;
                };
            budget = budget.checked_sub(normalized.len())?;
            if let Cow::Owned(updated) =
                Self::replace(&normalized, &needle, replacement, leading_word_boundary)?
            {
                normalized = Cow::Owned(updated);
            }
        }
        Some(normalized)
    }

    fn import(after_import: &str) -> Option<(&str, &str, &str)> {
        let source = Self::after_whitespace(after_import)?;
        let path_end = source
            .find(|ch| ch != '.' && !PythonText::word(ch))
            .unwrap_or(source.len());
        if path_end == 0 {
            return None;
        }
        let (original, remaining) = source.split_at(path_end);
        let remaining = Self::after_whitespace(remaining)?.strip_prefix("as")?;
        let value = Self::after_whitespace(remaining)?;
        let alias_end = value
            .find(|ch| !PythonText::word(ch))
            .unwrap_or(value.len());
        let (alias, end) = value.split_at(alias_end);
        (!alias.is_empty()).then_some((original, alias, end))
    }

    fn after_whitespace(text: &str) -> Option<&str> {
        let rest = text.trim_start_matches(PythonText::whitespace);
        (rest.len() < text.len()).then_some(rest)
    }

    fn replace<'a>(
        code: &'a str,
        needle: &str,
        replacement: &str,
        leading_word_boundary: bool,
    ) -> Option<Cow<'a, str>> {
        let mut updated = String::new();
        let mut previous_end = 0;
        for (start, matched) in code.match_indices(needle) {
            let end = start + matched.len();
            if (leading_word_boundary
                && code[..start]
                    .chars()
                    .next_back()
                    .is_some_and(PythonText::word))
                || code[end..].chars().next().is_some_and(PythonText::word)
            {
                continue;
            }
            // Avoid growing beyond the private transport size while expanding aliases.
            if updated.len() + start - previous_end + replacement.len() > 1024 * 1024 {
                return None;
            }
            updated.push_str(&code[previous_end..start]);
            updated.push_str(replacement);
            previous_end = end;
        }
        if previous_end == 0 {
            return Some(Cow::Borrowed(code));
        }
        if updated.len() + code.len() - previous_end > 1024 * 1024 {
            return None;
        }
        updated.push_str(&code[previous_end..]);
        Some(Cow::Owned(updated))
    }
}
