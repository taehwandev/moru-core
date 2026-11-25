//! owner: OverheadGlob; allowed imports: std directory enumeration and path matching;
//! forbidden imports: writes, subprocesses, recursion through **; callers/tests:
//! OverheadCollection and report CLI; verification: native/Python project discovery parity.
use std::{fs, path::PathBuf};

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
            let pattern = Pattern::parse(component)?;
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
    fn parse(text: &str) -> Option<Self> {
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
                    let negated = tail.first() == Some(&'!');
                    let start = usize::from(negated);
                    let search = start + usize::from(tail.get(start) == Some(&']'));
                    match tail[search..].iter().position(|&ch| ch == ']') {
                        Some(end) => {
                            let end = search + end;
                            index += end + 1;
                            Token::Class {
                                negated,
                                ranges: Self::ranges(&tail[start..end])?,
                            }
                        }
                        None => Token::Literal('['),
                    }
                }
                _ => Token::Literal(ch),
            };
            tokens.push(token);
        }
        Some(Self(tokens))
    }

    fn ranges(mut chars: &[char]) -> Option<Vec<(char, char)>> {
        let mut ranges = Vec::new();
        while let Some(&ch) = chars.first() {
            if let [start, '-', end, rest @ ..] = chars {
                // Python's regex translation renormalizes reversed ranges.
                // Keep that unusual profile on the reference path.
                if start > end {
                    return None;
                }
                ranges.push((*start, *end));
                chars = rest;
            } else {
                ranges.push((ch, ch));
                chars = &chars[1..];
            }
        }
        Some(ranges)
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
