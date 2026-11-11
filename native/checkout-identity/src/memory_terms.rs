//! owner: MemoryTerms; allowed imports: std/generated builder Unicode tables;
//! forbidden imports: filesystem, processes, stores, authority; callers/tests:
//! MemoryRecall and lexical parity probes; verification: Python corpus oracles.
use std::collections::BTreeSet;
include!(concat!(env!("OUT_DIR"), "/memory_contract.rs"));
type Terms = (BTreeSet<String>, BTreeSet<String>, BTreeSet<String>);
pub(crate) struct MemoryTerms;
const STOP: &str = "a an and are be before for in is it of on or the to use with src tests scripts";
const PARTICLES: &[&str] = &[
    "에서는",
    "으로는",
    "에게서",
    "에서",
    "에게",
    "으로",
    "까지",
    "부터",
    "처럼",
    "보다",
    "이랑",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "도",
    "로",
    "와",
    "과",
    "만",
    "랑",
];

impl MemoryTerms {
    pub(crate) fn version() -> &'static str {
        MEMORY_UNICODE
    }
    pub(crate) fn terms(text: &str) -> Terms {
        let chars: Vec<char> = text.chars().collect();
        let mut paths = BTreeSet::new();
        let mut rest = String::new();
        let mut index = 0;
        while index < chars.len() {
            if let Some(end) = Self::path_end(&chars, index) {
                let folded = Self::fold(&chars[index..end].iter().collect::<String>());
                paths.insert(
                    folded
                        .strip_prefix("./")
                        .unwrap_or(&folded)
                        .trim_end_matches('.')
                        .to_owned(),
                );
                rest.push(' ');
                index = end;
            } else {
                rest.push(chars[index]);
                index += 1;
            }
        }
        let mut stems = BTreeSet::new();
        let mut near = BTreeSet::new();
        for path in &paths {
            let parts: Vec<_> = path
                .split('/')
                .filter(|s| !s.is_empty() && *s != ".")
                .collect();
            let name = parts.last().copied().unwrap_or("");
            let stem = match name.rfind('.') {
                Some(n) if n > 0 && n < name.len() - 1 => &name[..n],
                _ => name,
            };
            stems.insert(stem.to_owned());
            for part in parts.iter().rev().skip(1).take(2) {
                near.insert((*part).to_owned());
            }
        }
        near.extend(stems.iter().cloned());
        let joined = format!("{rest} {}", near.into_iter().collect::<Vec<_>>().join(" "));
        let mut words: BTreeSet<_> = joined
            .split(|c| !Self::word(c) || c == '_')
            .filter(|word| word.chars().count() > 1)
            .map(Self::fold)
            .collect();
        let mut variants = Vec::new();
        for word in &words {
            if word.chars().any(|c| ('가'..='힣').contains(&c)) {
                if let Some(particle) = PARTICLES
                    .iter()
                    .find(|p| word.ends_with(**p) && word.chars().count() >= p.chars().count() + 2)
                {
                    variants.push(word[..word.len() - particle.len()].to_owned());
                }
            }
        }
        words.extend(variants);
        let mut modules = stems;
        for token in rest.split(|c| !Self::word(c) && c != '-') {
            // Python's two \b anchors trim non-word hyphens at either edge.
            let token = token.trim_matches('-');
            if token.contains(['_', '-'])
                || token
                    .as_bytes()
                    .windows(2)
                    .any(|pair| pair[0].is_ascii_lowercase() && pair[1].is_ascii_uppercase())
            {
                modules.insert(Self::fold(token));
            }
        }
        words.retain(|s| !STOP.split(' ').any(|stop| stop == s));
        modules.retain(|s| !STOP.split(' ').any(|stop| stop == s));
        (words, paths, modules)
    }
    pub(crate) fn score(text: &str, query: &Terms) -> usize {
        let (words, paths, modules) = Self::terms(text);
        let matches = paths
            .iter()
            .filter(|path| {
                query
                    .1
                    .iter()
                    .any(|other| other == *path || other.ends_with(&format!("/{path}")))
            })
            .count();
        let mut module_matches: BTreeSet<_> = modules
            .iter()
            .filter(|word| query.0.contains(*word) || query.2.contains(*word))
            .collect();
        module_matches.extend(query.2.intersection(&words));
        words.intersection(&query.0).count() + 12 * matches + 8 * module_matches.len()
    }
    fn word(c: char) -> bool {
        let cp = c as u32;
        WORD_RANGES
            .get(WORD_RANGES.partition_point(|(_, end)| *end < cp))
            .is_some_and(|(start, _)| *start <= cp)
    }
    fn fold(text: &str) -> String {
        let mut output = String::new();
        for c in text.chars() {
            if let Ok(i) = CASE_FOLDS.binary_search_by_key(&(c as u32), |(cp, _)| *cp) {
                output.push_str(CASE_FOLDS[i].1);
            } else {
                output.push(c);
            }
        }
        output
    }
    fn path_end(chars: &[char], start: usize) -> Option<usize> {
        let segment = |c| Self::word(c) || c == '.' || c == '-';
        let mut end = start;
        while end < chars.len() && segment(chars[end]) {
            end += 1;
        }
        if end == start {
            return None;
        }
        let mut slash = false;
        while end + 1 < chars.len() && chars[end] == '/' && segment(chars[end + 1]) {
            slash = true;
            end += 1;
            while end < chars.len() && segment(chars[end]) {
                end += 1;
            }
        }
        if slash {
            return Some(end);
        }
        end = start;
        while end < chars.len() && (Self::word(chars[end]) || chars[end] == '-') {
            end += 1;
        }
        if end == start || chars.get(end) != Some(&'.') {
            return None;
        }
        end += 1;
        let extension = end;
        while end < chars.len() && chars[end].is_ascii_alphanumeric() {
            end += 1;
        }
        (end > extension).then_some(end)
    }
}
