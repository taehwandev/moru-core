//! owner: matching removed line identities and classifying their review summary.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: source text, sample rendering, Git execution and mutations.
//! callers/tests: structural removal classification via private completion probe.
//! verification: global consumption, path ordering and first-seen ranking.
use serde_json::{json, Value};
use std::{
    cmp::Reverse,
    collections::{BTreeMap, HashMap},
};

pub(super) struct StructureRemovalMatching;

impl StructureRemovalMatching {
    const NONEMPTY: u64 = 1;
    const HEADING: u64 = 2;
    const MEANINGFUL: u64 = 4;

    pub(super) fn compare(input: &Value) -> Option<Value> {
        let mut available: HashMap<u64, BTreeMap<&str, usize>> = HashMap::new();
        for entry in input.get("added")?.as_array()? {
            let path = entry.get(0)?.as_str()?;
            for line in entry.get(1)?.as_array()? {
                *available
                    .entry(line.as_u64()?)
                    .or_default()
                    .entry(path)
                    .or_default() += 1;
            }
        }
        let mut matches = Vec::new();
        for entry in input.get("removed")?.as_array()? {
            let path = entry.get(0)?.as_str()?;
            let mut unmatched = Vec::new();
            let mut destinations: HashMap<&str, (usize, usize)> = HashMap::new();
            for (index, line) in entry.get(1)?.as_array()?.iter().enumerate() {
                if let Some(target) = Self::consume(available.get_mut(&line.as_u64()?), path) {
                    destinations.entry(target).or_insert((0, index)).0 += 1;
                } else {
                    unmatched.push(index);
                }
            }
            let mut ranked = destinations.into_iter().collect::<Vec<_>>();
            ranked.sort_unstable_by_key(|(_, (count, first))| (Reverse(*count), *first));
            let moved_to = ranked
                .into_iter()
                .take(3)
                .map(|(path, _)| path)
                .collect::<Vec<_>>();
            let mut row = json!({"unmatched": unmatched, "moved_to": moved_to});
            if let Some(limits) = input.get("summary") {
                let flags = entry.get(2)?.as_array()?;
                if flags.len() != entry.get(1)?.as_array()?.len() {
                    return None;
                }
                row["summary"] = Self::summary(flags, &unmatched, limits)?;
            }
            matches.push(row);
        }
        Some(json!({"matches": matches}))
    }

    fn summary(flags: &[Value], unmatched: &[usize], limits: &Value) -> Option<Value> {
        let headings = usize::try_from(limits.get("headings")?.as_u64()?).ok()?;
        let fallback = usize::try_from(limits.get("fallback")?.as_u64()?).ok()?;
        let flags = flags
            .iter()
            .map(Value::as_u64)
            .collect::<Option<Vec<_>>>()?;
        if flags.iter().any(|flag| !matches!(flag, 0 | 1 | 3 | 5 | 7)) {
            return None;
        }
        let classification = if flags.is_empty() {
            "unavailable"
        } else if unmatched.is_empty() && flags.iter().any(|flag| flag & Self::MEANINGFUL != 0) {
            "moved"
        } else {
            "removed"
        };
        let mut samples = Vec::new();
        if classification == "removed" {
            let candidates: Vec<_> = if unmatched.is_empty() {
                (0..flags.len()).collect()
            } else {
                unmatched.to_vec()
            };
            let is_heading = |&index: &usize| flags[index] & Self::HEADING != 0;
            if candidates.iter().any(is_heading) {
                samples.extend(candidates.into_iter().filter(is_heading).take(headings));
            } else {
                samples.extend(
                    candidates
                        .into_iter()
                        .filter(|&index| flags[index] & Self::NONEMPTY != 0)
                        .take(fallback),
                );
            }
        }
        Some(json!({"classification": classification, "samples": samples}))
    }

    fn consume<'a>(
        available: Option<&mut BTreeMap<&'a str, usize>>,
        source: &str,
    ) -> Option<&'a str> {
        let available = available?;
        let target = *available.keys().find(|path| **path != source)?;
        let count = available.get_mut(target)?;
        *count -= 1;
        if *count == 0 {
            available.remove(target);
        }
        Some(target)
    }
}
