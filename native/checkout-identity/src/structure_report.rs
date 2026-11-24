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
            Value::Object(values) => values.values().all(Self::supported),
            _ => true,
        }
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
