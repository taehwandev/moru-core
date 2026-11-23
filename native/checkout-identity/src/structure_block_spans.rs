//! owner: line-span calculation from structural starts and prepared line levels.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: source masking, filesystem, Git and approval decisions.
//! callers/tests: file diagnostic batch and structural parity fixtures.
//! verification: indentation, brace balance and strict length boundaries.
use serde_json::{json, Value};

pub(super) struct StructureBlockSpans;

impl StructureBlockSpans {
    pub(super) fn facts(input: &Value) -> Option<Value> {
        let raw = input.get("levels")?.as_array()?;
        let mut levels = Vec::with_capacity(raw.len() + 1);
        match input.get("kind")?.as_str()? {
            "indent" => {
                for level in raw {
                    levels.push(if level.is_null() {
                        None
                    } else {
                        Some(level.as_i64()?)
                    });
                }
            }
            "brace" => {
                let mut balance = 0i64;
                levels.push(Some(balance));
                for delta in raw {
                    balance = balance.checked_add(delta.as_i64()?)?;
                    levels.push(Some(balance));
                }
            }
            _ => return None,
        }
        let limit = input.get("limit")?.as_i64()?;
        let spans = Self::spans(&levels, raw.len());
        let mut current = Vec::new();
        for start in input.get("starts")?.as_array()? {
            let index = usize::try_from(start.get(0)?.as_u64()?).ok()?;
            let label = start.get(1)?.as_str()?;
            if index >= raw.len() || levels.get(index)?.is_none() {
                return None;
            }
            let span = spans.get(index).copied()?;
            if i64::try_from(span).ok()? > limit {
                current.push(json!({"line": index + 1, "label": label, "span": span}));
            }
        }
        Some(json!({
            "limit": limit,
            "initial": input.get("initial")?.as_bool()?,
            "current": current,
            "previous": [],
        }))
    }

    // The first later level no higher than this one ends the block. For
    // braces the levels are prefix balances, so a closing line is included.
    fn spans(levels: &[Option<i64>], line_count: usize) -> Vec<usize> {
        let mut next: Vec<(usize, i64)> = Vec::new();
        let mut spans = vec![0; levels.len()];
        for (index, level) in levels.iter().enumerate().rev() {
            let Some(level) = *level else { continue };
            while next.last().is_some_and(|(_, later)| *later > level) {
                next.pop();
            }
            let end = next.last().map_or(line_count, |(end, _)| *end);
            spans[index] = end - index;
            next.push((index, level));
        }
        spans
    }
}
