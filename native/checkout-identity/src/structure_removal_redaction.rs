//! owner: suppression and character limits for structural removal samples.
//! allowed imports: Python-compatible whitespace and standard text operations.
//! forbidden imports: I/O, logging and external communication.
//! callers/tests: removal analysis and Python reference redaction parity.
//! verification: Unicode folds, token length, URL userinfo and truncation order.
use crate::python_text::PythonText;

pub(super) struct StructureRemovalRedaction;

impl StructureRemovalRedaction {
    pub(super) fn sample(line: &str) -> String {
        if Self::sensitive(line) {
            "[sensitive-looking content omitted]".to_owned()
        } else {
            line.chars().take(100).collect()
        }
    }

    fn sensitive(line: &str) -> bool {
        let folded: String = line.chars().map(Self::fold).collect();
        const KEYWORDS: &[&str] = &[
            "password",
            "passphrase",
            "secret",
            "token",
            "credential",
            "authorization",
            "bearer",
            "-----begin",
        ];
        if KEYWORDS.iter().any(|word| folded.contains(word)) {
            return true;
        }
        for (prefix, name) in [
            ("api", "key"),
            ("private", "key"),
            ("database", "url"),
            ("connection", "string"),
        ] {
            if folded.match_indices(prefix).any(|(start, _)| {
                let tail = &folded[start + prefix.len()..];
                tail.strip_prefix(['_', '-'])
                    .unwrap_or(tail)
                    .starts_with(name)
            }) {
                return true;
            }
        }
        [("akia", 16), ("ghp_", 1), ("sk-", 1)]
            .iter()
            .any(|&(prefix, count)| {
                folded.match_indices(prefix).any(|(start, _)| {
                    let tail = &folded.as_bytes()[start + prefix.len()..];
                    tail.get(..count)
                        .is_some_and(|head| head.iter().all(u8::is_ascii_alphanumeric))
                })
            })
            || Self::identifier_run(&folded)
            || Self::url_userinfo(line)
    }

    fn fold(character: char) -> char {
        // Python re.IGNORECASE adds these folds to ASCII literal and range matches.
        match character {
            'İ' | 'ı' => 'i',
            'ſ' => 's',
            'K' => 'k',
            character => character.to_ascii_lowercase(),
        }
    }

    fn identifier_run(folded: &str) -> bool {
        let mut length = 0;
        for byte in folded.bytes() {
            if byte.is_ascii_alphanumeric() || b"+/=_-".contains(&byte) {
                length += 1;
                if length == 24 {
                    return true;
                }
            } else {
                length = 0;
            }
        }
        false
    }

    fn url_userinfo(line: &str) -> bool {
        line.match_indices("://").any(|(start, _)| {
            let tail = &line[start + 3..];
            let end = tail.find(|ch| ch == '/' || ch == '@' || PythonText::whitespace(ch));
            let Some(end) = end.filter(|&end| tail.as_bytes()[end] == b'@') else {
                return false;
            };
            tail[..end]
                .match_indices(':')
                .any(|(colon, _)| colon > 0 && colon + 1 < end)
        })
    }
}
