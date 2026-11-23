//! owner: Compose action dispatch and forwarding decisions and finding lines.
//! allowed imports: existing Compose scopes and source findings, Python text classes and collections.
//! forbidden imports: filesystem, Git, mutation and approval.
//! callers/tests: Kotlin mask probe and complete Python diagnostic parity.
//! verification: overlapping matches, leaf callbacks and scope exemptions.
use super::{
    kotlin_compose_callbacks::KotlinComposeCallbacks,
    kotlin_compose_source_findings::KotlinComposeSourceFindings,
    kotlin_compose_viewmodels::KotlinComposeViewModels,
};
use crate::python_text::PythonText;
use std::collections::{BTreeSet, HashSet};

pub(super) struct KotlinComposeActionFindings;

impl KotlinComposeActionFindings {
    pub(super) fn lines(code: &[char], bodies: &[[usize; 3]]) -> Option<BTreeSet<[usize; 2]>> {
        let newlines: Vec<_> = code
            .iter()
            .enumerate()
            .filter_map(|(i, &ch)| (ch == '\n').then_some(i))
            .collect();
        let mut findings = BTreeSet::new();
        let mut budget = 8_000_000usize;
        for &[signature, start, end] in bodies {
            let parameters = &code[signature..start];
            let body = &code[start..end];
            let names: HashSet<_> = KotlinComposeViewModels::names(parameters)
                .into_iter()
                .collect();
            let scopes = KotlinComposeCallbacks::regions(body, Some(&names));
            let scope_count = scopes.iter().map(Vec::len).sum::<usize>();
            budget = budget.checked_sub(body.len().checked_mul(1 + scope_count)?)?;
            let [events, data] = KotlinComposeSourceFindings::positions(body);
            let [dispatch, forwarding] = Self::positions(body, parameters, &names, &scopes);
            for (kind, offsets) in [events, data, dispatch, forwarding].into_iter().enumerate() {
                for offset in offsets {
                    let line = newlines.partition_point(|&index| index < start + offset) + 1;
                    findings.insert([line, kind]);
                }
            }
        }
        Some(findings)
    }

    fn positions(
        body: &[char],
        parameters: &[char],
        names: &HashSet<&[char]>,
        scopes: &[Vec<[usize; 2]>; 3],
    ) -> [Vec<usize>; 2] {
        let leaf = Self::leaf_callbacks(parameters);
        let mut dispatch = Vec::new();
        let mut forwarding = Vec::new();
        let (mut after_call, mut after_assignment, mut after_reference) = (0, 0, 0);
        let mut offset = 0;
        while offset < body.len() {
            let (word, tail) = Self::word(&body[offset..]);
            if word.is_empty() {
                offset += 1;
                continue;
            }
            let tail = Self::trim(tail);
            // The three legacy regex searches resume independently after a match.
            if offset >= after_call {
                if let Some((remaining, qualified)) = Self::call(word, tail) {
                    after_call = body.len() - remaining.len();
                    let receiver_allowed = names.contains(word)
                        || Self::equals(word, "viewModel")
                        || (word.len() > KotlinComposeViewModels::SUFFIX.len()
                            && word.ends_with(&KotlinComposeViewModels::SUFFIX));
                    let allowed = if qualified {
                        receiver_allowed
                    } else {
                        leaf.contains(word)
                    };
                    if !allowed && Self::outside_allowed_scope(offset, scopes) {
                        dispatch.push(offset);
                    }
                }
            }
            if offset >= after_assignment && Self::callback_name(word) {
                if let Some(rhs) = tail.strip_prefix(&['=']) {
                    let (name, remaining) = Self::word(Self::trim(rhs));
                    if Self::forwarded_name(name) && Self::trim(remaining).first() != Some(&'(') {
                        after_assignment = body.len() - remaining.len();
                        if !leaf.contains(name) {
                            forwarding.push(offset);
                        }
                    }
                }
            }
            if offset >= after_reference {
                if let Some(rhs) = tail.strip_prefix(&[':', ':']) {
                    let (name, remaining) = Self::word(Self::trim(rhs));
                    if Self::navigation_method(name) {
                        after_reference = body.len() - remaining.len();
                        if !names.contains(word)
                            && !Self::equals(word, "viewModel")
                            && !word.ends_with(&KotlinComposeViewModels::SUFFIX)
                        {
                            forwarding.push(offset);
                        }
                    }
                }
            }
            offset += word.len();
        }
        [dispatch, forwarding]
    }

    fn outside_allowed_scope(
        position: usize,
        [callbacks, hosts, collectors]: &[Vec<[usize; 2]>; 3],
    ) -> bool {
        let contains = |&[start, end]: &[usize; 2]| start <= position && position < end;
        if let Some(&[host, _]) = hosts.iter().find(|region| contains(region)) {
            if !callbacks
                .iter()
                .any(|region| region[0] > host && contains(region))
            {
                return false;
            }
        }
        callbacks.iter().any(contains) || !collectors.iter().any(contains)
    }

    fn call<'a>(word: &[char], tail: &'a [char]) -> Option<(&'a [char], bool)> {
        if let Some(member) = tail.strip_prefix(&['.']) {
            let (method, rest) = Self::word(Self::trim(member));
            if Self::navigation_method(method)
                || Self::forwarded_name(method)
                || (Self::equals(word, "Toast") && Self::equals(method, "makeText"))
            {
                return Self::trim(rest)
                    .strip_prefix(&['('])
                    .map(|rest| (rest, true));
            }
        }
        if Self::navigation_method(word) || Self::forwarded_name(word) {
            return tail.strip_prefix(&['(']).map(|rest| (rest, false));
        }
        None
    }

    fn leaf_callbacks(mut tail: &[char]) -> HashSet<&[char]> {
        let mut leaf = HashSet::new();
        while !tail.is_empty() {
            let (name, following) = Self::word(tail);
            if name.is_empty() {
                tail = &tail[1..];
                continue;
            }
            tail = following;
            if Self::callback_name(name) {
                if let Some(end) = Self::leaf_end(tail) {
                    leaf.insert(name);
                    tail = end;
                }
            }
        }
        leaf
    }

    fn leaf_end(code: &[char]) -> Option<&[char]> {
        let colon = Self::trim(code).strip_prefix(&[':'])?;
        let open = Self::trim(colon).strip_prefix(&['('])?;
        let close = Self::trim(open).strip_prefix(&[')'])?;
        let after_arrow = Self::trim(close).strip_prefix(&['-', '>'])?;
        let (name, rest) = Self::word(Self::trim(after_arrow));
        Self::equals(name, "Unit").then_some(rest)
    }

    fn callback_name(word: &[char]) -> bool {
        word.len() > 2 && word.starts_with(&['o', 'n'])
    }

    fn forwarded_name(word: &[char]) -> bool {
        word.get(..10)
            .is_some_and(|prefix| Self::equals(prefix, "onNavigate"))
            || [
                "onStartThread",
                "onRouteEvent",
                "onShowNotice",
                "onShowToast",
                "onShowAlert",
            ]
            .iter()
            .any(|name| Self::equals(word, name))
    }

    fn navigation_method(word: &[char]) -> bool {
        [
            "navigate",
            "popBackStack",
            "navigateUp",
            "showSnackbar",
            "showToast",
            "showNotice",
            "showAlert",
            "startActivity",
        ]
        .iter()
        .any(|name| Self::equals(word, name))
    }

    fn equals(word: &[char], text: &str) -> bool {
        word.len() == text.len() && word.iter().copied().eq(text.chars())
    }

    fn word(code: &[char]) -> (&[char], &[char]) {
        code.split_at(code.iter().take_while(|&&ch| PythonText::word(ch)).count())
    }

    fn trim(code: &[char]) -> &[char] {
        &code[code
            .iter()
            .take_while(|&&ch| PythonText::whitespace(ch))
            .count()..]
    }
}
