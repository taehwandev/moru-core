//! Owner: bounded staged_v1 commit-tree lookup; allowed: fixed local Git reads,
//! shared process capture and receipt hashing. Forbidden: Git writes, network,
//! receipt mutations and publication decisions. Caller: guarded completion probe.

use crate::{
    local_delivery_identity::LocalDeliveryIdentity, python_text::PythonText,
    read_process::capture_raw, text::Text,
};
use serde_json::{json, Value};
use std::{
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

const MAX_TREE: usize = 8 * 1024 * 1024;
const MAX_HISTORY: usize = 4 * 1024 * 1024;
const CANDIDATE_LIMIT: usize = 64;
const SEARCH_TIMEOUT: Duration = Duration::from_secs(6);

pub(crate) struct LocalDeliverySearch<'a> {
    project: &'a str,
    expected: &'a str,
    deadline: Instant,
}

impl LocalDeliverySearch<'_> {
    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let project = payload.get("project")?.as_str()?;
        let expected = payload.get("expected")?.as_str()?;
        let base = payload.get("base")?.as_str()?;
        let cached = payload.get("cached")?.as_str()?;
        let heads = payload.get("heads")?.as_array()?;
        if !Path::new(project).is_absolute()
            || expected.len() != 64
            || !Self::hex(expected)
            || !Self::oid(base)
            || (!cached.is_empty() && !Self::oid(cached))
            || heads.is_empty()
            || heads.len() > CANDIDATE_LIMIT
        {
            return None;
        }
        let heads: Vec<&str> = heads.iter().map(Value::as_str).collect::<Option<_>>()?;
        if heads.iter().any(|head| !Self::oid(head)) {
            return None;
        }
        let search = LocalDeliverySearch {
            project,
            expected,
            deadline: Instant::now() + SEARCH_TIMEOUT,
        };
        Some(json!({"commit": search.find(base, cached, &heads)?}))
    }

    fn find(&self, base: &str, cached: &str, heads: &[&str]) -> Option<String> {
        if !cached.is_empty() && self.matches(cached)? {
            return Some(cached.to_owned());
        }
        for head in heads {
            let range = format!("{base}..{head}");
            let history = self.git(
                &["rev-list", "--reverse", "--ancestry-path", &range],
                MAX_HISTORY,
            )?;
            for candidate in history.lines().take(CANDIDATE_LIMIT) {
                if !Self::oid(candidate) {
                    return None;
                }
                if self.matches(candidate)? {
                    return Some(candidate.to_owned());
                }
            }
        }
        Some(String::new())
    }

    fn matches(&self, oid: &str) -> Option<bool> {
        let tree = self.git(&["ls-tree", "-r", "-z", oid], MAX_TREE)?;
        Some(LocalDeliveryIdentity::digest(&tree, false)? == self.expected)
    }

    fn git(&self, args: &[&str], limit: usize) -> Option<String> {
        let remaining = self.deadline.checked_duration_since(Instant::now())?;
        let (stdout, stderr, success) = capture_raw(
            Command::new("git")
                .arg("-C")
                .arg(self.project)
                .args(args)
                .env("GIT_OPTIONAL_LOCKS", "0")
                .env("GIT_TERMINAL_PROMPT", "0")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_ALLOW_PROTOCOL", "")
                .stdin(Stdio::null()),
            remaining,
        )
        .ok()??;
        if !success || stdout.len() > limit || std::str::from_utf8(&stderr).is_err() {
            return None;
        }
        let text = Text::universal_newlines(std::str::from_utf8(&stdout).ok()?);
        Some(text.trim_matches(PythonText::whitespace).to_owned())
    }

    fn oid(value: &str) -> bool {
        matches!(value.len(), 40 | 64) && Self::hex(value)
    }

    fn hex(value: &str) -> bool {
        value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    }
}
