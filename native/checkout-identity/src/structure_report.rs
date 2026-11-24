//! owner: structural preview CLI and pre-review advisory rendering.
//! allowed imports: JSON, Python-compatible escaping and standard-library formatting.
//! forbidden imports: Git, source reads, approval, mutation and lifecycle state.
//! callers/tests: structural preview CLI, review advisory and parity fixtures.
//! verification: exact JSON output, exit status and bounded advisory order.
use crate::python_text::PythonText;
use serde_json::{json, Map, Value};

pub(super) struct StructureReport;

impl StructureReport {
    pub(super) fn render(input: &Value) -> Option<Value> {
        match input.get("mode")?.as_str()? {
            "error" => {
                let error = PythonText::json_ascii(input.get("error")?.as_str()?)?;
                Some(
                    json!({"text": format!(r#"{{"status": "FAIL", "error": {error}}}"#), "exit_code": 1}),
                )
            }
            "cli" => Self::cli(input),
            "advisory" => Self::advisory(input),
            "removal" => Self::removal(input),
            _ => None,
        }
    }

    fn cli(input: &Value) -> Option<Value> {
        let fields = input.get("fields")?;
        let failed = !fields.get("failures")?.as_array()?.is_empty();
        let mut report = Map::new();
        report.insert(
            "status".into(),
            json!(if failed { "FAIL" } else { "SUCCESS" }),
        );
        report.insert(
            "scope".into(),
            json!("Structural preview only; not behavior verification or review approval"),
        );
        for key in [
            "checked_paths",
            "failures",
            "warnings",
            "boundary_note_requirements",
            "net_deletions",
        ] {
            let value = fields.get(key)?;
            if !value.is_array() || !Self::supported(value) {
                return None;
            }
            report.insert(key.into(), value.clone());
        }
        let text = serde_json::to_string_pretty(&report).ok()?;
        Some(json!({"text": text, "exit_code": u8::from(failed)}))
    }

    fn supported(value: &Value) -> bool {
        match value {
            Value::Number(number) => number.is_i64() || number.is_u64(),
            Value::Array(values) => values.iter().all(Self::supported),
            Value::Object(values) => values.iter().all(|(key, value)| {
                Self::supported(value) || (key == "moved_ratio" && Self::hundredth(value))
            }),
            _ => true,
        }
    }

    fn hundredth(value: &Value) -> bool {
        // Removal ratios are Python-rounded hundredths from zero through one.
        // Both serializers use ordinary decimal notation over that range.
        value.as_f64().is_some_and(|ratio| {
            (0.0..=1.0).contains(&ratio) && (ratio * 100.0).round() / 100.0 == ratio
        })
    }

    fn removal(input: &Value) -> Option<Value> {
        let findings = input.get("findings")?.as_array()?;
        let limit = usize::try_from(input.get("char_limit")?.as_u64()?).ok()?;
        if findings.is_empty() {
            return Some(json!({"lines": []}));
        }
        let mut lines = vec![String::from(
            "measured net removals (review context, not a failure; compared with lines this diff added elsewhere):",
        )];
        let mut used = lines[0].chars().count();
        for (index, item) in findings.iter().enumerate() {
            let entry = Self::removal_entry(item)?;
            let size = entry.iter().map(|line| line.chars().count()).sum::<usize>();
            if used + size > limit {
                let remaining = findings.len() - index;
                lines.push(format!(
                    "  ... (+{remaining} more; all paths in structure_review.net_deletions)"
                ));
                break;
            }
            lines.extend(entry);
            used += size;
        }
        Some(json!({"lines": lines}))
    }

    fn removal_entry(item: &Value) -> Option<Vec<String>> {
        let path = item.get("path")?.as_str()?;
        let net = Self::integer(item.get("net")?)?;
        let head = format!("  {path}: net -{net}");
        match item.get("classification").and_then(Value::as_str) {
            Some("moved") => Some(vec![format!(
                "{head}, moved to {}",
                Self::strings(item.get("moved_to"))?.join(", ")
            )]),
            Some("removed") => {
                let destinations = Self::strings(item.get("moved_to"))?;
                let explanation = if destinations.is_empty() {
                    "not found elsewhere in this diff".to_owned()
                } else {
                    let unmatched = item
                        .get("unmatched_lines")
                        .map(Self::integer)
                        .unwrap_or(Some("0".into()))?;
                    format!(
                        "{unmatched} unmatched lines; other lines match at {}",
                        destinations.join(", ")
                    )
                };
                let mut lines = vec![format!("{head}, content removed ({explanation})")];
                lines.extend(
                    Self::strings(item.get("sample_lines"))?
                        .into_iter()
                        .map(|line| format!("    removed: {line}")),
                );
                Some(lines)
            }
            _ => {
                let removed = Self::integer(item.get("deletions")?)?;
                let added = Self::integer(item.get("additions")?)?;
                Some(vec![format!(
                    "{head} (-{removed} +{added}); review the diff for what was removed"
                )])
            }
        }
    }

    fn strings(value: Option<&Value>) -> Option<Vec<&str>> {
        match value {
            None | Some(Value::Null) => Some(Vec::new()),
            Some(value) => value.as_array()?.iter().map(Value::as_str).collect(),
        }
    }

    fn integer(value: &Value) -> Option<String> {
        (value.is_i64() || value.is_u64()).then(|| value.to_string())
    }

    fn advisory(input: &Value) -> Option<Value> {
        let count = input.get("changed_count")?.as_u64()?;
        let path_limit = input.get("path_limit")?.as_u64()?;
        let limit = usize::try_from(input.get("item_limit")?.as_u64()?).ok()?;
        let mut lines = Vec::new();
        if count > path_limit {
            lines.push(format!(
                "Review preview: working tree has {count} changed paths \
                 (default limit {path_limit}); pass --max-changed-paths {count} \
                 (or narrow scope with --review-scope pathspec --review-path <owned-path>) on review."
            ));
        }
        if let Some(summary) = Self::summary(input.get("failures")?, limit)? {
            lines.push(format!(
                "Review preview: structure review will fail on {summary}; fix before review."
            ));
        }
        if let Some(summary) = Self::summary(input.get("warnings")?, limit)? {
            lines.push(format!(
                "Review preview: review will require --structure-review-evidence because {summary}. \
                 In it, state per file whether the change expands its public owner surface \
                 and why the code stays there."
            ));
        }
        Some(json!({"lines": lines}))
    }

    fn summary(value: &Value, limit: usize) -> Option<Option<String>> {
        let items = value
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        if items.is_empty() {
            return Some(None);
        }
        let mut shown = items[..items.len().min(limit)].join("; ");
        if items.len() > limit {
            shown.push_str(&format!("; and {} more", items.len() - limit));
        }
        Some(Some(shown))
    }
}
