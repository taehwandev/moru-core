//! owner: Compose effect construction and data request positions.
//! allowed imports: Python-compatible text classes and standard-library slices.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Kotlin mask response and legacy diagnostic parity.
//! verification: lexical receiver boundaries, type checks and exact offsets.
use crate::python_text::PythonText;

pub(super) struct KotlinComposeSourceFindings;

impl KotlinComposeSourceFindings {
    pub(super) fn positions(body: &[char]) -> [Vec<usize>; 2] {
        let mut effects = Vec::new();
        let mut data = Vec::new();
        let (mut effect_end, mut data_end) = (0, 0);
        let mut start = 0;
        while start < body.len() {
            let length = Self::word_len(&body[start..]);
            if length == 0 {
                start += 1;
                continue;
            }
            let end = start + length;
            let word = &body[start..end];
            let tail = &body[end..];
            if start >= effect_end
                && Self::suffix(word, &["RouteEvent", "NavigationEvent", "NoticeEffect"])
            {
                if let Some(rest) = Self::trim(tail).strip_prefix(&['.']).map(Self::trim) {
                    if rest.first().is_some_and(char::is_ascii_uppercase) {
                        effect_end = body.len() - rest.len() + Self::word_len(rest);
                        if !Self::is_type_check(&body[..start]) {
                            effects.push(start);
                        }
                    }
                }
            }
            if start >= data_end {
                if let Some(rest) = Self::data_call(word, tail) {
                    data_end = body.len() - rest.len();
                    data.push(start);
                }
            }
            start = end;
        }
        [effects, data]
    }

    fn data_call<'a>(word: &[char], tail: &'a [char]) -> Option<&'a [char]> {
        let common = ["repository", "useCase", "api", "dao"]
            .iter()
            .any(|name| Self::equals(word, name));
        let tail = Self::trim(tail);
        if common || Self::suffix(word, &["Repository", "UseCase", "DataSource", "ApiClient"]) {
            if let Some(method) = tail
                .strip_prefix(&['?', '.'])
                .or_else(|| tail.strip_prefix(&['.']))
            {
                let method = Self::trim(method);
                let length = Self::word_len(method);
                if length > 0 {
                    return Self::trim(&method[length..]).strip_prefix(&['(']);
                }
            }
        }
        if common
            || (matches!(word[0], 'a'..='z' | '_')
                && word.len() > "UseCase".len()
                && Self::suffix(word, &["UseCase"]))
        {
            return tail.strip_prefix(&['(']);
        }
        None
    }

    fn is_type_check(before: &[char]) -> bool {
        let Some(last) = before.iter().rposition(|&ch| !PythonText::whitespace(ch)) else {
            return false;
        };
        let word_end = last + 1;
        let word_start = before[..word_end]
            .iter()
            .rposition(|&ch| !PythonText::word(ch))
            .map_or(0, |i| i + 1);
        matches!(&before[word_start..word_end], ['i' | 'a', 's'])
    }

    fn suffix(word: &[char], suffixes: &[&str]) -> bool {
        suffixes.iter().any(|suffix| {
            word.len() >= suffix.len() && Self::equals(&word[word.len() - suffix.len()..], suffix)
        })
    }

    fn equals(word: &[char], text: &str) -> bool {
        word.iter().copied().eq(text.chars())
    }

    fn word_len(code: &[char]) -> usize {
        code.iter().take_while(|&&ch| PythonText::word(ch)).count()
    }

    fn trim(code: &[char]) -> &[char] {
        let start = code
            .iter()
            .take_while(|&&ch| PythonText::whitespace(ch))
            .count();
        &code[start..]
    }
}
