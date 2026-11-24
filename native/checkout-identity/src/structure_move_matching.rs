//! owner: ordered line similarity for unstaged source moves and copies.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: filesystem, Git execution, writes and approval.
//! callers/tests: structural review through the private completion probe.
//! verification: Python SequenceMatcher parity for candidates and line counts.
use serde_json::{json, Value};
use std::collections::HashMap;

pub(super) struct StructureMoveMatching;

impl StructureMoveMatching {
    pub(super) const WORK_BUDGET: usize = 4_000_000;

    pub(super) fn compare(input: &Value) -> Option<Value> {
        let current = Self::lines(input.get("current")?)?;
        let candidates = input
            .get("candidates")?
            .as_array()?
            .iter()
            .map(Self::lines)
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"best": Self::best(&current, &candidates)?}))
    }

    pub(super) fn best(
        current: &[&str],
        candidates: &[Vec<&str>],
    ) -> Option<Option<(usize, usize)>> {
        let positions = Self::positions(current);
        // Bound repeated-line work in the probe; decline the whole request for Python replay.
        let mut budget = Self::WORK_BUDGET;
        let mut best = None;
        let mut best_ratio = -1.0;
        for (index, previous) in candidates.iter().enumerate() {
            let mut matched = 0;
            Self::matching_blocks(previous, current, &positions, &mut budget, |_, _, size| {
                matched += size;
            })?;
            let total = previous.len() + current.len();
            let ratio = if total == 0 {
                1.0
            } else {
                2.0 * matched as f64 / total as f64
            };
            if ratio > best_ratio {
                best_ratio = ratio;
                best = Some((index, matched));
            }
        }
        Some(best)
    }

    pub(super) fn lines(value: &Value) -> Option<Vec<&str>> {
        value.as_array()?.iter().map(Value::as_str).collect()
    }

    pub(super) fn positions<'a>(lines: &[&'a str]) -> HashMap<&'a str, Vec<usize>> {
        let mut positions: HashMap<&str, Vec<usize>> = HashMap::new();
        for (index, line) in lines.iter().enumerate() {
            positions.entry(line).or_default().push(index);
        }
        positions
    }

    pub(super) fn matching_blocks(
        previous: &[&str],
        current: &[&str],
        positions: &HashMap<&str, Vec<usize>>,
        budget: &mut usize,
        mut visit: impl FnMut(usize, usize, usize),
    ) -> Option<()> {
        if previous == current {
            if !current.is_empty() {
                visit(0, 0, current.len());
            }
            return Some(());
        }
        let mut pending = vec![(0, previous.len(), 0, current.len())];
        let mut prior_row = HashMap::new();
        let mut row = HashMap::new();
        // Split around each longest block as SequenceMatcher does with no junk/popular lines.
        while let Some((left, left_end, right, right_end)) = pending.pop() {
            *budget = budget.checked_sub(left_end - left)?;
            let (mut best_left, mut best_right, mut best_size) = (left, right, 0);
            prior_row.clear();
            for (offset, line) in previous[left..left_end].iter().enumerate() {
                row.clear();
                if let Some(indices) = positions.get(line) {
                    let start = indices.partition_point(|&index| index < right);
                    let end = indices.partition_point(|&index| index < right_end);
                    *budget = budget.checked_sub(end - start)?;
                    for &index in &indices[start..end] {
                        // Keys are one-based, so index zero has no prior diagonal.
                        let size = prior_row.get(&index).copied().unwrap_or(0) + 1;
                        row.insert(index + 1, size);
                        if size > best_size {
                            (best_left, best_right, best_size) =
                                (left + offset + 1 - size, index + 1 - size, size);
                        }
                    }
                }
                std::mem::swap(&mut row, &mut prior_row);
            }
            if best_size == 0 {
                continue;
            }
            visit(best_left, best_right, best_size);
            if left < best_left && right < best_right {
                pending.push((left, best_left, right, best_right));
            }
            let (after_left, after_right) = (best_left + best_size, best_right + best_size);
            if after_left < left_end && after_right < right_end {
                pending.push((after_left, left_end, after_right, right_end));
            }
        }
        Some(())
    }
}
