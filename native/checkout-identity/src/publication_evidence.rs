//! Owner: supplied upstream and provider evidence validation. Allowed: bounded
//! local file reads, JSON and text. Forbidden: Git, network, providers, writes
//! and authority decisions. Caller: guarded completion probe.

use crate::{
    python_input_file::{FileRead, PythonInputFile},
    python_text::PythonText,
};
use serde_json::{json, Value};
use std::path::Path;

const MAX_PROOF: u64 = 65_536;

pub(crate) struct PublicationEvidence;

impl PublicationEvidence {
    pub(crate) fn pull_request(payload: &Value) -> Option<Value> {
        let branch = payload.get("branch")?.as_str()?;
        let head = payload.get("head")?.as_str()?;
        let target = payload.get("target")?.as_str()?;
        let path = Path::new(payload.get("path")?.as_str()?);
        if branch.is_empty() {
            return None;
        }
        if path.metadata().ok()?.len() > MAX_PROOF {
            return Some(Self::refusal("the provider observation is too large"));
        }
        let bytes = match PythonInputFile::read(path.as_os_str(), MAX_PROOF, false)? {
            FileRead::Bytes(bytes) => bytes,
            FileRead::Error(_) => {
                return Some(Self::refusal(
                    "the provider observation could not be read as JSON",
                ))
            }
            FileRead::TooLarge => return None,
        };
        if std::str::from_utf8(&bytes).is_err() {
            return Some(Self::refusal(
                "the provider observation could not be read as JSON",
            ));
        }
        let answer: Value = serde_json::from_slice(&bytes).ok()?;
        if answer.get("exists").and_then(Value::as_bool) != Some(true) {
            return Some(Self::refusal(
                "no pull request was observed for this branch",
            ));
        }
        if [
            ("source_branch", branch),
            ("source_commit", head),
            ("target_branch", target),
        ]
        .iter()
        .any(|(key, value)| answer.get(key).and_then(Value::as_str) != Some(*value))
        {
            return Some(Self::refusal(
                "the observed pull request does not match this branch, reviewed commit and target",
            ));
        }
        match answer.get("state").and_then(Value::as_str) {
            Some(state @ ("OPEN" | "MERGED")) => Some(Self::observed(format!(
                "caller-observed pull request {state}: {branch}@{head} -> {target}"
            ))),
            _ => Some(Self::refusal(
                "the observed pull request is not open or merged",
            )),
        }
    }

    pub(crate) fn upstream(payload: &Value) -> Option<Value> {
        let remote = payload.get("remote")?.as_str()?;
        let merge = payload.get("merge")?.as_str()?;
        let head = payload.get("head")?.as_str()?;
        let listed = payload.get("listed")?.as_str()?;
        let first = listed
            .split(PythonText::whitespace)
            .find(|word| !word.is_empty());
        if first != Some(head) {
            return Some(Self::refusal("the upstream branch does not point at HEAD"));
        }
        Some(Self::observed(format!("{remote} {merge} is {head}")))
    }

    fn observed(observation: String) -> Value {
        json!({"observation": observation, "reason": ""})
    }

    fn refusal(reason: &str) -> Value {
        json!({"observation": "", "reason": reason})
    }
}
