//! owner: inherited Compose diagnostic matching on unchanged baseline lines.
//! allowed imports: shared line matching, JSON and standard-library collections.
//! forbidden imports: source IO, Git, mutation and approval.
//! callers/tests: structural review private completion probe and Compose fixtures.
//! verification: shifted, edited and repeated findings with ordered Python parity.
use super::structure_move_matching::StructureMoveMatching;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};

pub(super) struct StructureActionDelta;

impl StructureActionDelta {
    pub(super) fn classify(input: &Value) -> Option<Value> {
        let previous = StructureMoveMatching::lines(input.get("previous")?)?;
        let current = StructureMoveMatching::lines(input.get("current")?)?;
        let mut prior = BTreeMap::<usize, Vec<&str>>::new();
        for key in input.get("prior_keys")?.as_array()? {
            if !key.is_null() {
                let (line, reason) = Self::key(key)?;
                prior.entry(line).or_default().push(reason);
            }
        }
        let mut inherited = HashSet::new();
        let positions = StructureMoveMatching::positions(&current);
        let mut budget = StructureMoveMatching::WORK_BUDGET;
        StructureMoveMatching::matching_blocks(
            &previous,
            &current,
            &positions,
            &mut budget,
            |left, right, size| {
                // Block indexes are zero-based; diagnostics use one-based lines.
                for (&line, reasons) in prior.range((left + 1)..=(left + size)) {
                    inherited.extend(
                        reasons
                            .iter()
                            .map(|&reason| (right + (line - left), reason)),
                    );
                }
            },
        )?;
        let flags = input
            .get("current_keys")?
            .as_array()?
            .iter()
            .map(|key| {
                if key.is_null() {
                    Some(false)
                } else {
                    Some(inherited.contains(&Self::key(key)?))
                }
            })
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"inherited": flags}))
    }

    fn key(value: &Value) -> Option<(usize, &str)> {
        let line = usize::try_from(value.get(0)?.as_u64()?).ok()?;
        Some((line, value.get(1)?.as_str()?))
    }
}
