//! owner: VerificationRender; allowed imports: Verification, VerificationSelectors, serde_json;
//! forbidden imports: git, filesystem, writes, subprocess; callers/tests: Verification;
//! verification: pure JSON, command, omission, and coverage rendering parity.
use super::{Verification, VerificationSelectors, RUNNER_SELECTOR_LIMIT};
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub(super) struct VerificationRender;

impl VerificationRender {
    pub(super) fn push_omission(
        omissions: &mut Vec<Value>,
        seen: &mut BTreeSet<(String, String, String)>,
        kind: &str,
        path: &str,
        reason: &str,
        count: Option<usize>,
    ) {
        let key = (kind.to_owned(), path.to_owned(), reason.to_owned());
        if seen.insert(key) {
            let mut item = json!({"kind": kind, "path": path, "reason": reason});
            if let Some(n) = count {
                item["count"] = json!(n);
            }
            omissions.push(item);
        }
    }

    pub(super) fn build_commands(
        compile_batch: &[String],
        modules: &[String],
        fallback_command: Option<&str>,
    ) -> Vec<String> {
        let mut commands = Vec::new();
        if !compile_batch.is_empty() {
            let quoted = compile_batch
                .iter()
                .map(|p| VerificationSelectors::compile_arg_quote(p))
                .collect::<Vec<_>>()
                .join(" ");
            commands.push(format!("python3 -B -m py_compile {quoted}"));
        }
        if !modules.is_empty() {
            for chunk in modules.chunks(RUNNER_SELECTOR_LIMIT) {
                let args = chunk
                    .iter()
                    .map(|m| VerificationSelectors::sh_quote(m))
                    .collect::<Vec<_>>()
                    .join(" ");
                commands.push(format!(
                    "PYTHONPATH=tests:scripts python3 -B -m unittest {args}"
                ));
            }
        } else if let Some(command) = fallback_command {
            commands.push(command.to_owned());
        }
        commands
    }

    pub(super) fn coverage_note(has_selectors: bool, has_compile: bool) -> String {
        if has_selectors {
            "Selected tests cover only matched Python test targets; they do not prove full-suite or non-Python coverage.".to_owned()
        } else if has_compile {
            "Changed Python files have no verified full-suite coverage; inspect unmatched files explicitly.".to_owned()
        } else {
            String::new()
        }
    }

    pub(super) fn apply_active_verify(
        verification: &mut Verification,
        launcher: &str,
        project: &str,
        rules: &str,
        evidence: &str,
    ) -> Option<String> {
        if verification.next_batch.is_empty() {
            return None;
        }
        let mut parts = vec![
            VerificationSelectors::sh_quote(launcher),
            "verify".to_owned(),
            "--project".to_owned(),
            VerificationSelectors::sh_quote(project),
            "--rules".to_owned(),
            VerificationSelectors::sh_quote(rules),
            "--evidence".to_owned(),
            VerificationSelectors::sh_quote(evidence),
        ];
        for selector in verification.next_batch.iter().take(RUNNER_SELECTOR_LIMIT) {
            parts.push("--test-selector".to_owned());
            parts.push(VerificationSelectors::sh_quote(selector));
        }
        let verify_cmd = parts.join(" ");
        verification
            .commands
            .retain(|c| !c.starts_with("PYTHONPATH=tests:scripts python3 -B -m unittest "));
        verification.commands.push(verify_cmd.clone());
        verification.verify_command = Some(verify_cmd.clone());
        if !verification.remaining_selectors.is_empty() {
            verification.batch_status = Some(format!(
                "bounded batch 1 ({} of {} selectors); {} remaining selectors must also be verified before the tests gate is complete",
                verification.next_batch.len(),
                verification.selectors.len(),
                verification.remaining_selectors.len()
            ));
        }
        Some(verify_cmd)
    }

    pub(super) fn json(verification: &Verification) -> String {
        let mut map = serde_json::Map::new();
        if let Some(status) = &verification.batch_status {
            map.insert("batch_status".into(), json!(status));
        }
        map.insert("changed_paths".into(), json!(verification.paths));
        map.insert("coverage_note".into(), json!(verification.coverage_note));
        map.insert("matched_test_modules".into(), json!(verification.modules));
        map.insert("next_verify_batch".into(), json!(verification.next_batch));
        map.insert("omissions".into(), json!(verification.omissions));
        map.insert(
            "remaining_test_selectors".into(),
            json!(verification.remaining_selectors),
        );
        map.insert("suggested_commands".into(), json!(verification.commands));
        map.insert("test_selectors".into(), json!(verification.selectors));
        if let Some(cmd) = &verification.verify_command {
            map.insert("verify_command".into(), json!(cmd));
        }
        Self::canonical_json(&Value::Object(map))
    }

    fn canonical_json(value: &Value) -> String {
        match value {
            Value::Object(map) => {
                let mut keys: Vec<&String> = map.keys().collect();
                keys.sort();
                format!(
                    "{{{}}}",
                    keys.iter()
                        .map(|k| format!(
                            "{}: {}",
                            serde_json::to_string(k).unwrap(),
                            Self::canonical_json(&map[*k])
                        ))
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            }
            Value::Array(values) => format!(
                "[{}]",
                values
                    .iter()
                    .map(Self::canonical_json)
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            _ => serde_json::to_string(value).unwrap(),
        }
    }
}
