//! owner: Compose callback and lifecycle host scopes over prepared bodies.
//! allowed imports: shared Python text classes and standard-library slices.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Kotlin mask response and Python regex/brace parity fixtures.
//! verification: nested, malformed, Unicode and lifecycle host scopes.
use crate::python_text::PythonText;

pub(super) struct KotlinComposeCallbacks;

impl KotlinComposeCallbacks {
    pub(super) fn regions(body: &[char]) -> [Vec<[usize; 2]>; 2] {
        let mut ends = vec![body.len(); body.len()];
        let mut braces = Vec::new();
        let mut open = Vec::new();
        let mut last_token = None;
        for (index, &ch) in body.iter().enumerate() {
            match ch {
                '{' => {
                    braces.push((index, last_token));
                    open.push(index);
                }
                '}' => {
                    braces.push((index, last_token));
                    if let Some(start) = open.pop() {
                        ends[start] = index + 1;
                    }
                }
                _ => {}
            }
            if !PythonText::whitespace(ch) {
                last_token = Some(index);
            }
        }

        let mut callbacks = Vec::new();
        let mut hosts = Vec::new();
        let mut callback_cursor = 0;
        let mut index = 0;
        while index < body.len() {
            let length = Self::word_len(&body[index..]);
            if length == 0 {
                index += 1;
                continue;
            }
            let end = index + length;
            let word = &body[index..end];
            if index >= callback_cursor {
                let start = if word.starts_with(&['o', 'n']) && length > 2 {
                    Self::after(&body[end..], '=')
                        .and_then(|rest| Self::after(rest, '{'))
                        .map(|rest| body.len() - rest.len() - 1)
                } else if Self::equals(word, "clickable") || Self::equals(word, "combinedClickable")
                {
                    Self::clickable(body, end, &braces)
                } else {
                    None
                };
                if let Some(start) = start {
                    callbacks.push([start, ends[start]]);
                    // finditer resumes just after the opening brace, not after the body.
                    callback_cursor = start + 1;
                }
            }
            if Self::equals(word, "NoticeEffectLifecycleCollector") {
                if let Some(rest) = Self::host(&body[end..]) {
                    let start = body.len() - rest.len() - 1;
                    hosts.push([start, ends[start]]);
                }
            }
            index = end;
        }
        [callbacks, hosts]
    }

    fn clickable(body: &[char], end: usize, braces: &[(usize, Option<usize>)]) -> Option<usize> {
        let rest = Self::trim(&body[end..]);
        let start = body.len() - rest.len();
        match rest.first()? {
            '{' => Some(start),
            '(' => {
                // The legacy regex admits any brace-free arguments followed by a final
                // ')' before '{', even when the inner parentheses are unbalanced.
                let &(brace, preceding) =
                    braces.get(braces.partition_point(|&(i, _)| i < start))?;
                (body[brace] == '{' && body[preceding?] == ')').then_some(brace)
            }
            _ => None,
        }
    }

    fn host(rest: &[char]) -> Option<&[char]> {
        let rest = Self::after(rest, '(')?;
        let rest = Self::after_word(rest, "effects")?;
        let rest = Self::trim(Self::after(rest, '=')?);
        let name_len = Self::word_len(rest);
        if name_len == 0 {
            return None;
        }
        let rest = Self::after(&rest[name_len..], ',')?;
        let rest = Self::after_word(rest, "onEffect")?;
        Self::after(Self::after(rest, '=')?, '{')
    }

    fn after_word<'a>(rest: &'a [char], word: &str) -> Option<&'a [char]> {
        let rest = Self::trim(rest);
        let length = Self::word_len(rest);
        Self::equals(&rest[..length], word).then_some(&rest[length..])
    }

    fn after(rest: &[char], token: char) -> Option<&[char]> {
        Self::trim(rest).strip_prefix(&[token])
    }

    fn trim(code: &[char]) -> &[char] {
        let start = code
            .iter()
            .take_while(|&&ch| PythonText::whitespace(ch))
            .count();
        &code[start..]
    }

    fn word_len(code: &[char]) -> usize {
        code.iter().take_while(|&&ch| PythonText::word(ch)).count()
    }

    fn equals(code: &[char], word: &str) -> bool {
        code.len() == word.len() && code.iter().copied().eq(word.chars())
    }
}
