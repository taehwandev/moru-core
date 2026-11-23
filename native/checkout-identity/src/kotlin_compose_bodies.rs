//! owner: lexical Compose function ranges over masked Kotlin.
//! allowed imports: shared Python text classes and standard-library slices.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Kotlin mask probe and Python range parity.
//! verification: annotation boundaries, signature nesting and expression stops.
use crate::python_text::PythonText;

pub(super) struct KotlinComposeBodies;

impl KotlinComposeBodies {
    pub(super) fn ranges(code: &[char], unicode: &str) -> Option<Vec<[usize; 3]>> {
        if !PythonText::matches_unicode_version(unicode) && code.iter().any(|ch| !ch.is_ascii()) {
            return None;
        }
        let mut budget = 4_000_000usize;
        let mut ranges = Vec::new();
        for (index, &ch) in code.iter().enumerate() {
            if ch != '@' {
                continue;
            }
            let tail = &code[index + 1..];
            let annotation = Self::prefix(tail, "androidx.compose.runtime.Composable")
                .or_else(|| Self::prefix(tail, "Composable"));
            let Some(length) = annotation else { continue };
            let after = index + 1 + length;
            if code.get(after).is_some_and(|&ch| PythonText::word(ch)) {
                continue;
            }
            // Each annotation can scan the suffix for a declaration and balanced body.
            budget = budget.checked_sub(code.len() - after)?;
            if let Some(range) = Self::body(code, after) {
                ranges.push(range);
            }
        }
        Some(ranges)
    }

    fn body(code: &[char], after: usize) -> Option<[usize; 3]> {
        let mut signature = None;
        for index in after..code.len() {
            if matches!(code[index], '{' | '}' | '=') {
                return None;
            }
            if code[index] == 'f' && (index == after || !PythonText::word(code[index - 1])) {
                if let Some(offset) = Self::declaration(&code[index..]) {
                    signature = Some(index + offset);
                    break;
                }
            }
        }
        let signature = signature?;
        let mut start = Self::close(code, signature, '(', ')');
        start += Self::skip(&code[start..], PythonText::whitespace);
        if code.get(start) == Some(&':') {
            start += 1;
            start += Self::skip(&code[start..], PythonText::whitespace);
            let length = Self::skip(&code[start..], |ch| {
                PythonText::word(ch) || matches!(ch, '?' | '.' | '<' | '>')
            });
            if length == 0 {
                return None;
            }
            start += length;
            start += Self::skip(&code[start..], PythonText::whitespace);
        }
        let end = match code.get(start)? {
            '{' => Self::close(code, start, '{', '}'),
            '=' => Self::expression_end(code, start),
            _ => return None,
        };
        Some([signature, start, end])
    }

    fn declaration(code: &[char]) -> Option<usize> {
        let prefix = Self::prefix(code, "fun")?;
        let spaces = Self::skip(&code[prefix..], PythonText::whitespace);
        if spaces == 0 {
            return None;
        }
        let mut end = prefix + spaces;
        let word = Self::skip(&code[end..], PythonText::word);
        if word == 0 {
            return None;
        }
        end += word;
        if code.get(end) == Some(&'.') {
            end += 1;
            let name = Self::skip(&code[end..], PythonText::word);
            if name == 0 {
                return None;
            }
            end += name;
        }
        end += Self::skip(&code[end..], PythonText::whitespace);
        (code.get(end) == Some(&'(')).then_some(end)
    }

    fn close(code: &[char], start: usize, opening: char, closing: char) -> usize {
        let mut depth = 0;
        for (index, &ch) in code.iter().enumerate().skip(start) {
            if ch == opening {
                depth += 1;
            } else if ch == closing {
                depth -= 1;
                if depth == 0 {
                    return index + 1;
                }
            }
        }
        code.len()
    }

    fn expression_end(code: &[char], start: usize) -> usize {
        for (index, &ch) in code.iter().enumerate().skip(start) {
            if ch != '\n' {
                continue;
            }
            let tail = &code[index + 1..];
            if tail.first() == Some(&'@')
                || ["fun", "private fun", "internal fun"]
                    .iter()
                    .any(|keyword| {
                        Self::prefix(tail, keyword).is_some_and(|len| {
                            !tail.get(len).is_some_and(|&ch| PythonText::word(ch))
                        })
                    })
            {
                return index;
            }
        }
        code.len()
    }

    fn prefix(code: &[char], keyword: &str) -> Option<usize> {
        let candidate = code.get(..keyword.len())?;
        candidate
            .iter()
            .copied()
            .eq(keyword.chars())
            .then_some(candidate.len())
    }

    fn skip(code: &[char], predicate: impl Fn(char) -> bool) -> usize {
        code.iter().take_while(|&&ch| predicate(ch)).count()
    }
}
