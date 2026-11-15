//! Private scanner for the CodexStatusLine owner; no IO or TOML normalization.
use super::CodexStatusLine;
impl CodexStatusLine {
    pub(super) fn headers(text: &str) -> Vec<(usize, usize, &str)> {
        let mut offset = 0;
        let mut result = Vec::new();
        for line in text.split('\n') {
            let body = line.trim_start_matches([' ', '\t']);
            if let Some(body) = body.strip_prefix('[') {
                if let Some(end) = body.find(']') {
                    let after = body[end + 1..].trim_start_matches([' ', '\t']);
                    if end > 0 && (after.is_empty() || after.starts_with('#')) {
                        result.push((offset, offset + line.len(), &body[..end]));
                    }
                }
            }
            offset += line.len() + 1;
        }
        result
    }

    pub(super) fn assignments(text: &str, key: &str) -> Vec<usize> {
        let mut offset = 0;
        let mut result = Vec::new();
        for line in text.split('\n') {
            let body = line.trim_start_matches([' ', '\t']);
            if let Some(rest) = body.strip_prefix(key) {
                let rest = rest.trim_start_matches([' ', '\t']);
                if rest.starts_with('=') {
                    result.push(offset + line.len() - rest.len() + 1);
                }
            }
            offset += line.len() + 1;
        }
        result
    }

    pub(super) fn array_end(text: &str, opening: usize) -> Option<usize> {
        let (mut quote, mut escaped, mut comment, mut depth) = (None, false, false, 0);
        for (index, c) in text.char_indices().filter(|(index, _)| *index >= opening) {
            if comment {
                if c == '\n' {
                    comment = false;
                }
                continue;
            }
            if let Some(q) = quote {
                if q == '"' && escaped {
                    escaped = false;
                } else if q == '"' && c == '\\' {
                    escaped = true;
                } else if c == q {
                    quote = None;
                }
                continue;
            }
            if c == '#' {
                comment = true;
            } else if text[index..].starts_with("\"\"\"") || text[index..].starts_with("'''") {
                return None;
            } else if c == '"' || c == '\'' {
                quote = Some(c);
            } else if c == '[' {
                depth += 1;
            } else if c == ']' {
                depth -= 1;
                if depth == 0 {
                    return Some(index);
                }
            }
        }
        None
    }

    pub(super) fn items(body: &str) -> Option<Vec<&str>> {
        let mut items = Vec::new();
        let mut iter = body.char_indices().peekable();
        let mut expect = true;
        while let Some((index, c)) = iter.next() {
            if Self::space(c) {
                continue;
            }
            if c == '#' {
                for (_, c) in iter.by_ref() {
                    if c == '\n' {
                        break;
                    }
                }
                continue;
            }
            if !expect {
                if c != ',' {
                    return None;
                }
                expect = true;
                continue;
            }
            if (c != '"' && c != '\'')
                || body[index..].starts_with("\"\"\"")
                || body[index..].starts_with("'''")
            {
                return None;
            }
            let start = index + 1;
            let mut escaped = false;
            let mut closing = None;
            for (end, next) in iter.by_ref() {
                if c == '"' && escaped {
                    escaped = false;
                } else if c == '"' && next == '\\' {
                    escaped = true;
                } else if next == c {
                    closing = Some(end);
                    break;
                }
            }
            items.push(&body[start..closing?]);
            expect = false;
        }
        Some(items)
    }

    pub(super) fn last_syntax(body: &str) -> Option<usize> {
        let (mut quote, mut escaped, mut comment, mut last) = (None, false, false, None);
        for (index, c) in body.char_indices() {
            if comment {
                if c == '\n' {
                    comment = false;
                }
                continue;
            }
            if let Some(q) = quote {
                last = Some(index + c.len_utf8());
                if q == '"' && escaped {
                    escaped = false;
                } else if q == '"' && c == '\\' {
                    escaped = true;
                } else if c == q {
                    quote = None;
                }
                continue;
            }
            if c == '#' {
                comment = true;
            } else if c == '"' || c == '\'' {
                quote = Some(c);
                last = Some(index + 1);
            } else if !Self::space(c) {
                last = Some(index + c.len_utf8());
            }
        }
        last
    }
}
