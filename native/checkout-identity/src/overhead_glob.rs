//! owner: OverheadGlob; allowed imports: std directory enumeration and path matching;
//! forbidden imports: writes, subprocesses, recursion through **; callers/tests:
//! OverheadCollection and report CLI; verification: native/Python project discovery parity.
use std::{collections::VecDeque, fs, path::PathBuf};

pub(super) struct OverheadGlob;
impl OverheadGlob {
    pub(super) fn directories(path: &str) -> Option<Vec<PathBuf>> {
        if !Self::has_pattern(path) {
            return Some(vec![PathBuf::from(if path.is_empty() {
                "."
            } else {
                path
            })]);
        }
        let mut parents = vec![PathBuf::from(if path.starts_with('/') { "/" } else { "." })];
        for component in path.split('/').filter(|part| !part.is_empty()) {
            if !Self::has_pattern(component) {
                for parent in &mut parents {
                    parent.push(component);
                }
                continue;
            }
            let pattern = Pattern::parse(component);
            let include_hidden = component.starts_with('.');
            let mut children = Vec::new();
            for parent in parents {
                let Ok(entries) = fs::read_dir(parent) else {
                    continue;
                };
                for entry in entries {
                    let Ok(entry) = entry else {
                        break;
                    };
                    let path = entry.path();
                    if path.is_dir() {
                        let name = entry.file_name();
                        let name = name.to_str()?;
                        if (include_hidden || !name.starts_with('.')) && pattern.matches(name) {
                            children.push(path);
                        }
                    }
                }
            }
            parents = children;
        }
        Some(parents)
    }

    fn has_pattern(text: &str) -> bool {
        text.contains(['*', '?', '['])
    }
}

enum Token {
    Star,
    Any,
    Literal(char),
    Class {
        negated: bool,
        ranges: Vec<(char, char)>,
    },
}
impl Token {
    fn accepts(&self, ch: char) -> bool {
        match self {
            Self::Star => false,
            Self::Any => true,
            Self::Literal(expected) => *expected == ch,
            Self::Class { negated, ranges } => {
                ranges
                    .iter()
                    .any(|&(start, end)| (start..=end).contains(&ch))
                    != *negated
            }
        }
    }
}

struct Pattern(Vec<Token>);
impl Pattern {
    fn parse(text: &str) -> Self {
        let chars: Vec<_> = text.chars().collect();
        let mut tokens = Vec::new();
        let mut index = 0;
        while let Some(&ch) = chars.get(index) {
            index += 1;
            let token = match ch {
                '*' => Token::Star,
                '?' => Token::Any,
                '[' => {
                    let tail = &chars[index..];
                    let start = usize::from(tail.first() == Some(&'!'));
                    let search = start + usize::from(tail.get(start) == Some(&']'));
                    match tail[search..].iter().position(|&ch| ch == ']') {
                        Some(end) => {
                            let end = search + end;
                            index += end + 1;
                            Self::character_class(&tail[..end])
                        }
                        None => Token::Literal('['),
                    }
                }
                _ => Token::Literal(ch),
            };
            tokens.push(token);
        }
        Self(tokens)
    }

    fn character_class(chars: &[char]) -> Token {
        let mut terms = Vec::new();
        let mut begin = 0;
        let mut search = 1 + usize::from(chars.first() == Some(&'!'));
        while let Some(hyphen) = chars
            .get(search..)
            .and_then(|tail| tail.iter().position(|&ch| ch == '-'))
            .map(|index| search + index)
        {
            if hyphen + 1 == chars.len() {
                break;
            }
            terms.push(&chars[begin..hyphen]);
            begin = hyphen + 1;
            search = hyphen + 3;
        }
        terms.push(&chars[begin..]);

        // The reference removes descending endpoints from right to left.
        // After removal, a surviving leading '!' can become the negation.
        let mut normalized: Vec<VecDeque<char>> = Vec::new();
        for term in terms.into_iter().rev() {
            if let Some(right) = normalized.last_mut() {
                if term.last().zip(right.front()).is_some_and(|(a, b)| a > b) {
                    right.pop_front();
                    for &ch in term[..term.len() - 1].iter().rev() {
                        right.push_front(ch);
                    }
                    continue;
                }
            }
            normalized.push(term.iter().copied().collect());
        }
        let negated = normalized.last().and_then(VecDeque::front) == Some(&'!');
        if negated {
            normalized.last_mut().unwrap().pop_front();
        }
        let mut ranges = Vec::new();
        let mut previous = None;
        for term in normalized.into_iter().rev() {
            if let Some((start, &end)) = previous.zip(term.front()) {
                ranges.push((start, end));
            }
            previous = term.back().copied();
            ranges.extend(term.into_iter().map(|ch| (ch, ch)));
        }
        Token::Class { negated, ranges }
    }

    fn matches(&self, text: &str) -> bool {
        let chars: Vec<_> = text.chars().collect();
        let (mut token, mut letter) = (0, 0);
        let mut star = None;
        while letter < chars.len() {
            match self.0.get(token) {
                Some(Token::Star) => {
                    token += 1;
                    star = Some((token, letter));
                }
                Some(next) if next.accepts(chars[letter]) => {
                    token += 1;
                    letter += 1;
                }
                _ => {
                    let Some((next, start)) = star else {
                        return false;
                    };
                    token = next;
                    letter = start + 1;
                    star = Some((next, letter));
                }
            }
        }
        self.0[token..]
            .iter()
            .all(|token| matches!(token, Token::Star))
    }
}
