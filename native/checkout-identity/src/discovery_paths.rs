//! Owner: ordinary explicit request-path candidates, preserving Python grammar.
//! Allowed: std and existing filesystem/candidate readers.
//! Forbidden: shell execution, variable expansion, writes, scope or launch policy.
//! Callers/tests: discovery_search; native request-path tests and bundle smoke.
use crate::{discovery_candidates::Candidates, discovery_fs::DiscoveryFs as Fs};
use std::{collections::BTreeSet, path::Path};

pub(crate) struct RequestPaths;

impl RequestPaths {
    pub(crate) fn add(request: &str, cwd: &Path, candidates: &mut Candidates) -> Option<()> {
        for token in Self::tokens(request)? {
            // Match the canonical strip set exactly, including leading dots.
            let cleaned = token.trim_matches(|c| "\"'`.,;:)]}<>".contains(c));
            if cleaned.is_empty() || !cleaned.starts_with(['/', '~', '.']) {
                continue;
            }
            let path = Fs::expand(Path::new(cleaned))?;
            let path = if path.is_absolute() {
                path
            } else {
                cwd.join(path)
            };
            if !Fs::exists(&path)? {
                continue;
            }
            let Some(root) = Fs::root(&path)? else {
                continue;
            };
            let (files, markers) = Fs::facts(&root)?;
            candidates.add(
                root,
                files,
                markers,
                130,
                "explicit path in request",
                "request_path",
                &[],
            )?;
        }
        Some(())
    }

    fn tokens(request: &str) -> Option<BTreeSet<&str>> {
        // For this closed subset shlex has no quoting/escaping work to do.
        // Unusual whitespace stays Python-owned: shlex and regex differ there.
        if request.contains(['\'', '"', '\\', '`', '$'])
            || request.chars().any(|c| {
                (c.is_control() || c.is_whitespace()) && ![' ', '\t', '\r', '\n'].contains(&c)
            })
        {
            return None;
        }
        let mut tokens: BTreeSet<_> = request
            .split([' ', '\t', '\r', '\n'])
            .filter(|v| !v.is_empty())
            .collect();
        // Equivalent to (?:~|/|\.)[^\s,;:]+ for the subset admitted above.
        // Include embedded paths as well as complete whitespace-delimited words.
        let mut tail = request;
        while let Some(start) = tail.find(['~', '/', '.']) {
            let value = &tail[start..];
            let end = value
                .char_indices()
                .skip(1)
                .find(|(_, c)| c.is_whitespace() || [',', ';', ':'].contains(c))
                .map_or(value.len(), |(index, _)| index);
            if end > 1 {
                tokens.insert(&value[..end]);
                tail = &value[end..];
            } else {
                tail = &value[1..];
            }
        }
        Some(tokens)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordinary_words_and_embedded_path_matches_share_a_set() {
        let tokens =
            RequestPaths::tokens("진행 /one,/two;prefix(/three):line\n~/four . /one").unwrap();
        for expected in [
            "/one,/two;prefix(/three):line",
            "/one",
            "/two",
            "/three)",
            "~/four",
            ".",
        ] {
            assert!(tokens.contains(expected), "{expected}");
        }
        assert!(!tokens.contains("/"));
        assert!(!tokens.contains(". /one"));
    }

    #[test]
    fn complex_quoting_expansion_and_non_shlex_whitespace_defer() {
        for request in [
            "'/one two'",
            "\"/one\"",
            "/one\\ two",
            "$ROOT",
            "`pwd`",
            "x\u{a0}/one",
            "x\u{1c}/one",
        ] {
            assert!(RequestPaths::tokens(request).is_none(), "{request}");
        }
    }
}
