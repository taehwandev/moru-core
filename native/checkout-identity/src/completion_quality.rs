//! Owner: advisory quality checks on recorded verification commands.
//! Allowed: std/serde_json. Forbidden: execution, authority, writes and inference.
//! Callers/tests: completion_process; native completion tests.
use serde_json::{json, Value};

pub(crate) struct Quality;

impl Quality {
    pub(crate) fn inspect(value: &Value) -> Option<Value> {
        let records = value.get("records")?.as_array()?;
        if records.len() > 128 {
            return None;
        }
        let mut warnings = Vec::new();
        for record in records {
            if record.get("status")?.as_str()? != "SUCCESS" {
                continue;
            }
            let gate = record.get("gate")?.as_str()?;
            if gate.len() > 100 || gate.chars().any(char::is_control) {
                return None;
            }
            let Some(fields) = record.get("fields").and_then(Value::as_object) else {
                continue;
            };
            let command = fields
                .get("check")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim();
            let literal = !command.contains([';', '&', '|', '$', '`', '\n', '\r', '#', '<', '>']);
            let fixed = matches!(command, "true" | ":" | "exit 0")
                || (literal
                    && matches!(command.split_whitespace().next(), Some("echo" | "printf")));
            if fixed {
                warnings.push(json!({"gate":gate,"rule":"fixed_output_check"}));
            }
            let result = fields
                .get("result")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_lowercase();
            let words: Vec<_> = result
                .split(|c: char| !c.is_ascii_alphanumeric())
                .filter(|v| !v.is_empty())
                .collect();
            let compact = result.split_whitespace().collect::<String>();
            let explicit_zero =
                ["tests=0", "tests:0", "cases=0", "cases:0"]
                    .iter()
                    .any(|pattern| {
                        compact.match_indices(pattern).any(|(start, _)| {
                            !compact
                                .as_bytes()
                                .get(start + pattern.len())
                                .is_some_and(u8::is_ascii_digit)
                        })
                    });
            if explicit_zero
                || words
                    .windows(2)
                    .any(|v| matches!(v, ["0", "test" | "tests" | "cases"]))
            {
                warnings.push(json!({"gate":gate,"rule":"zero_test_count"}));
            }
        }
        Some(json!({"warnings":warnings}))
    }
}
