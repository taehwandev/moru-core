//! Owner: bounded literal argv recognition for native read-query ingress.
//! Allowed: std only. Forbidden: expansion, execution, shell evaluation, policy.
//! Callers/tests: FileQuery, pretool_query; native query callback tests.
//! Verification: quote/option boundaries, expansion and concatenation rejection.
pub(crate) struct LiteralArgs;

impl LiteralArgs {
    pub(crate) fn parse(command: &str) -> Option<Vec<String>> {
        if command.len() > 16 * 1024 || command.chars().any(|c| c.is_control() && c != '\t') {
            return None;
        }
        let mut rest = command.trim_matches([' ', '\t']);
        let mut words = Vec::new();
        while !rest.is_empty() {
            let prefix = ["--format=", "--pretty=", "--glob="]
                .into_iter()
                .find(|prefix| {
                    rest.strip_prefix(*prefix)
                        .is_some_and(|v| v.starts_with(['\'', '"']))
                });
            let offset = prefix.map_or(0, str::len);
            let quoted = rest[offset..].starts_with(['\'', '"']);
            let (word, tail) = if quoted {
                if words.is_empty() {
                    return None;
                }
                let quote = rest.as_bytes()[offset];
                let end = offset + 1 + rest[offset + 1..].find(quote as char)?;
                let value = &rest[offset + 1..end];
                if (prefix.is_none() && value.starts_with('-'))
                    || value.chars().any(char::is_control)
                    || value.contains(['$', '`'])
                    || (quote == b'"' && value.contains('\\'))
                {
                    return None;
                }
                (format!("{}{value}", prefix.unwrap_or("")), &rest[end + 1..])
            } else {
                let end = rest.find([' ', '\t']).unwrap_or(rest.len());
                let value = &rest[..end];
                if value.starts_with('~')
                    || !value
                        .chars()
                        .all(|c| c.is_alphanumeric() || "_./-:=%,+@~^".contains(c))
                {
                    return None;
                }
                (value.to_owned(), &rest[end..])
            };
            if !tail.is_empty() && !tail.starts_with([' ', '\t']) {
                return None;
            }
            words.push(word);
            if words.len() > 20 {
                return None;
            }
            rest = tail.trim_start_matches([' ', '\t']);
        }
        Some(words)
    }
}
