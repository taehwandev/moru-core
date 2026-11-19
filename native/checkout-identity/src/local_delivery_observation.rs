//! Owner: read-only staged_v1 branch/commit observation. Allowed: bounded Git
//! search and JSON bridge. Forbidden: receipts, publication authority and writes.
//! Caller: guarded completion probe; tests use real Git refs and receipt checks.

use crate::local_delivery_search::LocalDeliveryGit;
use serde_json::{json, Value};

const INTEGRATE: &str = "publication.integrate/";

pub(crate) struct LocalDeliveryObservation;

impl LocalDeliveryObservation {
    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let project = payload.get("project")?.as_str()?;
        let expected = payload.get("expected")?.as_str()?;
        let base = payload.get("base")?.as_str()?;
        let source = payload.get("source")?.as_str()?;
        let cached = payload.get("cached")?.as_str()?;
        let checkpoint = payload.get("checkpoint")?.as_str()?;
        let declared = payload.get("commit_declared")?.as_bool()?;
        let targets = payload.get("targets")?.as_array()?;
        if !LocalDeliveryGit::oid(base) || !LocalDeliveryGit::digest(expected) || targets.len() > 64
        {
            return None;
        }
        let targets: Vec<&str> = targets.iter().map(Value::as_str).collect::<Option<_>>()?;
        let search = LocalDeliveryGit::new(project)?;
        let heads = Self::reachable_heads(&search, base, source, &targets)?;
        if heads.is_empty() {
            return Some(Self::refusal("local delivery proof cannot be verified"));
        }
        let commit = if declared {
            let cached = Self::eligible_cache(&search, base, cached, &heads)?;
            search.find(base, cached, &heads, expected)?
        } else {
            base.to_owned()
        };
        if commit.is_empty() {
            return Some(Self::refusal(
                "the reviewed staged content has not been observed in a commit",
            ));
        }
        if let Some(target) = checkpoint.strip_prefix(INTEGRATE) {
            if !targets.contains(&target) {
                return Some(Self::refusal("local integration target was not prepared"));
            }
            if let Some(head) = search.branch(target)? {
                if search.ancestor(&commit, &head)? {
                    return Some(Self::observed(format!(
                        "target {target} contains reviewed commit {commit}"
                    )));
                }
            }
            return Some(Self::refusal(
                "target branch does not contain the reviewed commit",
            ));
        }
        if checkpoint == "publication.commit" {
            return Some(Self::observed(format!(
                "reviewed staged content committed as {commit}"
            )));
        }
        Some(Self::refusal("not a local delivery checkpoint"))
    }

    fn reachable_heads(
        search: &LocalDeliveryGit<'_>,
        base: &str,
        source: &str,
        targets: &[&str],
    ) -> Option<Vec<String>> {
        let heads = match search.branch(source)? {
            Some(head) => vec![head],
            None => targets
                .iter()
                .map(|target| search.branch(target))
                .collect::<Option<Vec<_>>>()?
                .into_iter()
                .flatten()
                .collect(),
        };
        let mut reachable = Vec::new();
        for head in heads {
            if search.ancestor(base, &head)? {
                reachable.push(head);
            }
        }
        Some(reachable)
    }

    fn eligible_cache<'a>(
        search: &LocalDeliveryGit<'_>,
        base: &str,
        cached: &'a str,
        heads: &[String],
    ) -> Option<&'a str> {
        if !LocalDeliveryGit::oid(cached) || !search.ancestor(base, cached)? {
            return Some("");
        }
        for head in heads {
            if search.ancestor(cached, head)? {
                return Some(cached);
            }
        }
        Some("")
    }

    fn observed(text: String) -> Value {
        json!({"observation": text, "reason": ""})
    }

    fn refusal(text: &str) -> Value {
        json!({"observation": "", "reason": text})
    }
}
