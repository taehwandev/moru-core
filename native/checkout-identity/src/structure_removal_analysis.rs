//! owner: local structural removal analysis across parsed patches and line matching.
//! allowed imports: bounded removal inputs, identity matcher, and Python text boundaries.
//! forbidden imports: Git mutations, source logging, and external communication.
//! callers/tests: structural removal explanation and forced-Python parity fixtures.
//! verification: shared occurrence consumption, heading precedence and selected samples only.
use super::{
    structure_diff_acquisition::StructureDiffAcquisition,
    structure_removal_inputs::StructureRemovalInputs,
    structure_removal_matching::StructureRemovalMatching,
    structure_removal_redaction::StructureRemovalRedaction,
};
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::collections::HashMap;

pub(super) struct StructureRemovalAnalysis;

impl StructureRemovalAnalysis {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let paths = input.get("findings")?.as_array()?;
        let limits = input.get("summary")?;
        let parsed = match input.get("diff") {
            Some(text) => StructureRemovalInputs::from_patch(input, text.as_str()?)?,
            None => StructureRemovalInputs::from_patch(
                input,
                &StructureDiffAcquisition::removal_patch(input)?,
            )?,
        };
        if parsed.get("truncated") == Some(&Value::Bool(true)) {
            return Some(parsed);
        }
        let removed = parsed.get("removed")?.as_object()?;
        let added = parsed.get("added")?.as_object()?;
        let mut identities = HashMap::new();
        let mut removal_rows = Vec::new();
        let mut original_lines = Vec::new();
        for path in paths {
            let path = path.as_str()?;
            let lines = removed
                .get(path)
                .and_then(Value::as_array)
                .map_or(&[][..], Vec::as_slice);
            let ids = Self::identities(lines, &mut identities)?;
            let flags = lines
                .iter()
                .map(|line| line.as_str().map(Self::flags))
                .collect::<Option<Vec<_>>>()?;
            removal_rows.push(json!([path, ids, flags]));
            original_lines.push(lines);
        }
        let mut addition_rows = Vec::new();
        for (path, lines) in added {
            addition_rows.push(json!([
                path,
                Self::identities(lines.as_array()?, &mut identities)?
            ]));
        }
        let matched = StructureRemovalMatching::compare(&json!({
            "removed": removal_rows, "added": addition_rows, "summary": limits,
        }))?;
        let mut findings = Vec::new();
        for (lines, row) in original_lines
            .into_iter()
            .zip(matched.get("matches")?.as_array()?)
        {
            findings.push(Self::finding(lines, row)?);
        }
        Some(json!({"findings": findings}))
    }

    fn finding(lines: &[Value], row: &Value) -> Option<Value> {
        if lines.is_empty() {
            return Some(json!({"classification": "unavailable"}));
        }
        let unmatched = row.get("unmatched")?.as_array()?.len();
        // Round the binary64 ratio directly to two decimal places like Python.
        // Scaling the ratio first can round a near-half value onto the tie.
        let ratio = lines.len().checked_sub(unmatched)? as f64 / lines.len() as f64;
        let moved_ratio: f64 = format!("{ratio:.2}").parse().ok()?;
        let moved_to = row.get("moved_to")?;
        let summary = row.get("summary")?;
        match summary.get("classification")?.as_str()? {
            "moved" => Some(json!({
                "classification": "moved", "moved_ratio": moved_ratio, "moved_to": moved_to,
            })),
            "removed" => {
                let mut samples = Vec::new();
                for index in summary.get("samples")?.as_array()? {
                    let index = usize::try_from(index.as_u64()?).ok()?;
                    let line = lines
                        .get(index)?
                        .as_str()?
                        .trim_matches(PythonText::whitespace);
                    samples.push(StructureRemovalRedaction::sample(line));
                }
                Some(json!({
                    "classification": "removed",
                    "moved_ratio": moved_ratio,
                    "unmatched_lines": unmatched,
                    "moved_to": moved_to,
                    "sample_lines": samples,
                }))
            }
            _ => None,
        }
    }

    fn identities<'a>(
        lines: &'a [Value],
        known: &mut HashMap<&'a str, usize>,
    ) -> Option<Vec<usize>> {
        lines
            .iter()
            .map(|line| {
                let next = known.len();
                Some(*known.entry(line.as_str()?).or_insert(next))
            })
            .collect()
    }

    fn flags(line: &str) -> u8 {
        let line = line.trim_matches(PythonText::whitespace);
        let heading = line.starts_with('#')
            || line.ends_with(':')
            || ["def ", "async def ", "class ", "function "]
                .iter()
                .any(|prefix| line.starts_with(prefix));
        u8::from(!line.is_empty())
            | (u8::from(heading) << 1)
            | (u8::from(line.chars().take(4).count() == 4) << 2)
    }
}
