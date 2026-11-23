//! owner: line-span calculation from structural starts and prepared line levels.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: source masking, filesystem, Git and approval decisions.
//! callers/tests: file diagnostic batch and structural parity fixtures.
//! verification: indentation, brace balance and strict length boundaries.
use super::structure_python_blocks::StructurePythonBlocks;
use super::structure_style_blocks::StructureStyleBlocks;
use serde_json::{json, Value};

pub(super) struct StructureBlockSpans;

impl StructureBlockSpans {
    pub(super) fn batch(input: &Value) -> Option<Value> {
        let files = input.get("files")?.as_array()?;
        if files.len() > 4096 {
            return None;
        }
        let blocks = files
            .iter()
            .map(Self::records)
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"blocks": blocks}))
    }

    pub(super) fn facts(input: &Value) -> Option<Value> {
        Some(json!({
            "limit": input.get("limit")?.as_i64()?,
            "initial": input.get("initial")?.as_bool()?,
            "current": Self::records(input)?,
            "previous": [],
        }))
    }

    pub(super) fn records(input: &Value) -> Option<Vec<Value>> {
        let kind = input.get("kind")?.as_str()?;
        let limit = input.get("limit")?.as_i64()?;
        if kind == "python-source" {
            let lines = input.get("lines")?.as_array()?;
            let (levels, starts) = StructurePythonBlocks::prepare(lines)?;
            return Self::measure(&levels, lines.len(), starts, limit);
        }
        if kind == "style-source" {
            let lines = input.get("lines")?.as_array()?;
            let (deltas, labels) = StructureStyleBlocks::prepare(lines)?;
            let levels = Self::brace_levels(deltas.into_iter().map(Some))?;
            let starts = labels
                .iter()
                .map(|(line, label)| (*line, label.as_str()))
                .collect();
            return Self::measure(&levels, lines.len(), starts, limit);
        }
        let raw = input.get("levels")?.as_array()?;
        let mut levels = Vec::with_capacity(raw.len() + 1);
        match kind {
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
                levels = Self::brace_levels(raw.iter().map(Value::as_i64))?;
            }
            _ => return None,
        }
        let mut starts = Vec::new();
        for start in input.get("starts")?.as_array()? {
            let index = usize::try_from(start.get(0)?.as_u64()?).ok()?;
            let label = start.get(1)?.as_str()?;
            starts.push((index, label));
        }
        Self::measure(&levels, raw.len(), starts, limit)
    }

    fn brace_levels(deltas: impl IntoIterator<Item = Option<i64>>) -> Option<Vec<Option<i64>>> {
        let mut balance = 0i64;
        let mut levels = vec![Some(balance)];
        for delta in deltas {
            balance = balance.checked_add(delta?)?;
            levels.push(Some(balance));
        }
        Some(levels)
    }

    fn measure(
        levels: &[Option<i64>],
        line_count: usize,
        starts: Vec<(usize, &str)>,
        limit: i64,
    ) -> Option<Vec<Value>> {
        let spans = Self::spans(levels, line_count);
        let mut current = Vec::new();
        for (index, label) in starts {
            if index >= line_count || levels.get(index)?.is_none() {
                return None;
            }
            let span = spans.get(index).copied()?;
            if i64::try_from(span).ok()? > limit {
                current.push(json!({"line": index + 1, "label": label, "span": span}));
            }
        }
        Some(current)
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
