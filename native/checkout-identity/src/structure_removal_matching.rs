//! owner: matching removed line identities to available additions.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: source text, sample output, Git execution and mutations.
//! callers/tests: structural removal classification via private completion probe.
//! verification: global consumption, path ordering and first-seen ranking.
use serde_json::{json, Value};
use std::{
    cmp::Reverse,
    collections::{BTreeMap, HashMap},
};

pub(super) struct StructureRemovalMatching;

impl StructureRemovalMatching {
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
            matches.push(json!({"unmatched": unmatched, "moved_to": moved_to}));
        }
        Some(json!({"matches": matches}))
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
