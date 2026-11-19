//! Owner: local Git preconditions of legacy publication receipts. Allowed:
//! bounded local Git and JSON. Forbidden: contacting remotes, provider calls,
//! state writes and granting publication authority. Caller: completion probe.

use crate::local_delivery_search::LocalDeliveryGit;
use serde_json::{json, Value};

pub(crate) struct LegacyPublicationHead;

impl LegacyPublicationHead {
    pub(crate) fn upstream(payload: &Value) -> Option<Value> {
        let git = LocalDeliveryGit::new(payload.get("project")?.as_str()?)?;
        let missing = || json!({"remote": "", "merge": ""});
        let (status, branch) = git.run(&["symbolic-ref", "--short", "HEAD"], 64 * 1024)?;
        if status != 0 || branch.is_empty() {
            return Some(missing());
        }
        let remote_key = format!("branch.{branch}.remote");
        let merge_key = format!("branch.{branch}.merge");
        let (remote_status, remote) = git.run(&["config", &remote_key], 64 * 1024)?;
        let (merge_status, merge) = git.run(&["config", &merge_key], 64 * 1024)?;
        if remote_status != 0
            || merge_status != 0
            || remote.is_empty()
            || !merge.starts_with("refs/heads/")
        {
            return Some(missing());
        }
        if remote.starts_with('-') {
            return None;
        }
        Some(json!({"remote": remote, "merge": merge}))
    }

    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let project = payload.get("project")?.as_str()?;
        let source = payload.get("source")?.as_str()?;
        let base = payload.get("base")?.as_str()?;
        let requires_commit = payload.get("requires_commit")?.as_bool()?;
        if !LocalDeliveryGit::oid(base) {
            return None;
        }
        let git = LocalDeliveryGit::new(project)?;
        if source.is_empty() {
            return Some(Self::refusal("source branch was not recorded; re-prepare this publication under current authority"));
        }
        let args = ["symbolic-ref", "--quiet", "--short", "HEAD"];
        match git.run(&args, 64 * 1024)? {
            (0, branch) if branch == source => {}
            (0 | 1, _) => {
                return Some(Self::refusal(
                    "source branch differs from the finished publication",
                ))
            }
            _ => return None,
        }
        let head = git.git(&["rev-parse", "HEAD"], 4096)?;
        if !LocalDeliveryGit::oid(&head) {
            return None;
        }
        let advanced = head != base && git.ancestor(base, &head)?;
        if requires_commit {
            if !advanced {
                return Some(Self::refusal(
                    "HEAD has not advanced from the finished commit base",
                ));
            }
        } else if head != base {
            return Some(Self::refusal(
                "HEAD is not the reviewed finish commit and no declared commit covers it",
            ));
        }
        if !git
            .git(
                &["status", "--porcelain", "--untracked-files=no"],
                1024 * 1024,
            )?
            .is_empty()
        {
            return Some(Self::refusal("tracked changes remain uncommitted"));
        }
        Some(json!({"head": head, "reason": ""}))
    }

    fn refusal(reason: &str) -> Value {
        json!({"head": "", "reason": reason})
    }
}
