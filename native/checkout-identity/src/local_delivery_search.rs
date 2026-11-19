//! Owner: bounded staged_v1 Git inspection; allowed: fixed local Git reads,
//! shared process capture and receipt hashing. Forbidden: Git writes, network,
//! receipt mutations and publication decisions. Caller: guarded completion probe.

use crate::{
    local_delivery_identity::LocalDeliveryIdentity, python_text::PythonText,
    read_process::status::capture_status, text::Text,
};
use std::{
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

pub(super) const MAX_TREE: usize = 8 * 1024 * 1024;
const MAX_HISTORY: usize = 4 * 1024 * 1024;
const CANDIDATE_LIMIT: usize = 64;
const SEARCH_TIMEOUT: Duration = Duration::from_secs(6);

pub(super) struct LocalDeliveryGit<'a> {
    project: &'a str,
    deadline: Instant,
}

impl<'a> LocalDeliveryGit<'a> {
    pub(super) fn new(project: &'a str) -> Option<Self> {
        if !Path::new(project).is_absolute() {
            return None;
        }
        Some(Self {
            project,
            deadline: Instant::now() + SEARCH_TIMEOUT,
        })
    }

    pub(super) fn find(
        &self,
        base: &str,
        cached: &str,
        heads: &[String],
        expected: &str,
    ) -> Option<String> {
        if !cached.is_empty() && self.matches(cached, expected)? {
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
                if self.matches(candidate, expected)? {
                    return Some(candidate.to_owned());
                }
            }
        }
        Some(String::new())
    }

    fn matches(&self, oid: &str, expected: &str) -> Option<bool> {
        let tree = self.git(&["ls-tree", "-r", "-z", oid], MAX_TREE)?;
        Some(LocalDeliveryIdentity::digest(&tree, false)? == expected)
    }

    pub(super) fn git(&self, args: &[&str], limit: usize) -> Option<String> {
        let (status, text) = self.run(args, limit)?;
        (status == 0).then_some(text)
    }

    pub(super) fn branch(&self, name: &str) -> Option<Option<String>> {
        let reference = format!("refs/heads/{name}");
        match self.run(&["rev-parse", "--verify", &reference], 4096)? {
            (0, text) if Self::oid(&text) => Some(Some(text)),
            (128, _) => {
                let (status, _) =
                    self.run(&["show-ref", "--verify", "--quiet", &reference], 4096)?;
                (status == 1).then_some(None)
            }
            _ => None,
        }
    }

    pub(super) fn ancestor(&self, commit: &str, head: &str) -> Option<bool> {
        match self
            .run(&["merge-base", "--is-ancestor", commit, head], 4096)?
            .0
        {
            0 => Some(true),
            1 => Some(false),
            _ => None,
        }
    }

    pub(super) fn run(&self, args: &[&str], limit: usize) -> Option<(i32, String)> {
        let remaining = self.deadline.checked_duration_since(Instant::now())?;
        let (stdout, stderr, status) = capture_status(
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
        if stdout.len() > limit || std::str::from_utf8(&stderr).is_err() {
            return None;
        }
        let text = Text::universal_newlines(std::str::from_utf8(&stdout).ok()?);
        Some((
            status.code()?,
            text.trim_matches(PythonText::whitespace).to_owned(),
        ))
    }

    pub(super) fn oid(value: &str) -> bool {
        matches!(value.len(), 40 | 64) && Self::hex(value)
    }

    pub(super) fn digest(value: &str) -> bool {
        value.len() == 64 && Self::hex(value)
    }

    fn hex(value: &str) -> bool {
        value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    }
}
