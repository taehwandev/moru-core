//! owner: typed ViewModel receiver names in one Compose signature.
//! allowed imports: shared Python text classes and standard-library slices.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Compose scope response and Python signature parity.
//! verification: dotted type backtracking, Unicode names and signature isolation.
use crate::python_text::PythonText;

pub(super) struct KotlinComposeViewModels;

impl KotlinComposeViewModels {
    pub(super) const SUFFIX: [char; 9] = ['V', 'i', 'e', 'w', 'M', 'o', 'd', 'e', 'l'];

    pub(super) fn names(mut rest: &[char]) -> Vec<&[char]> {
        let mut names = Vec::new();
        while !rest.is_empty() {
            let size = Self::word_len(rest);
            if size == 0 {
                rest = &rest[1..];
                continue;
            }
            let (name, tail) = rest.split_at(size);
            rest = tail;
            if let Some(after_colon) = Self::trim(tail).strip_prefix(&[':']) {
                if let Some(end) = Self::type_end(Self::trim(after_colon)) {
                    names.push(name);
                    // finditer resumes at the end of the chosen type component.
                    rest = end;
                }
            }
        }
        names
    }

    fn type_end(mut rest: &[char]) -> Option<&[char]> {
        let mut end = None;
        loop {
            let length = Self::word_len(rest);
            if length == 0 {
                return end;
            }
            let (part, following) = rest.split_at(length);
            if part.ends_with(&Self::SUFFIX) {
                // A later dotted component takes precedence; retain the last
                // match if the regex would backtrack to an earlier component.
                end = Some(following);
            }
            let Some(next) = following.strip_prefix(&['.']) else {
                return end;
            };
            rest = next;
        }
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
}
