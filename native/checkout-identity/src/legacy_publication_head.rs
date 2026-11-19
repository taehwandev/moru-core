//! Owner: local Git preconditions of legacy publication receipts. Allowed:
//! bounded local Git and JSON. Forbidden: contacting remotes, provider calls,
//! state writes and granting publication authority. Caller: completion probe.

use crate::local_delivery_search::LocalDeliveryGit;
use serde_json::{json, Value};

pub(crate) struct LegacyPublicationHead;

impl LegacyPublicationHead {
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
