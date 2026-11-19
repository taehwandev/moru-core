//! Owner: local Git receipt preparation. Allowed: bounded Git inspection,
//! canonical paths and staged identity hashing. Forbidden: writing refs/index or
//! receipts, network and publication authority. Caller: completion probe.

use crate::{
    local_delivery_identity::LocalDeliveryIdentity,
    local_delivery_search::{LocalDeliveryGit, MAX_TREE},
};
use serde_json::{json, Map, Value};

const INTEGRATE: &str = "publication.integrate/";

pub(crate) struct LocalDeliveryPrepare;

impl LocalDeliveryPrepare {
    pub(crate) fn probe(payload: &Value) -> Option<Value> {
        let project = payload.get("project")?.as_str()?;
        let base = payload.get("base")?.as_str()?;
        let source = payload.get("source")?.as_str()?;
        let checkpoints = payload.get("checkpoints")?.as_array()?;
        if !LocalDeliveryGit::oid(base) || checkpoints.len() > 64 {
            return None;
        }
        let checkpoints: Vec<&str> = checkpoints
            .iter()
            .map(Value::as_str)
            .collect::<Option<_>>()?;
        let git = LocalDeliveryGit::new(project)?;
        match git
            .run(
                &[
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--quiet",
                    "--exit-code",
                ],
                4096,
            )?
            .0
        {
            0 => {}
            1 => {
                return Some(Self::refusal(
                    "tracked worktree content must match the reviewed index",
                ))
            }
            _ => return None,
        }
        let index = git.git(&["ls-files", "--stage", "-z"], MAX_TREE)?;
        let staged = LocalDeliveryIdentity::digest(&index, true)?;
        let tree = git.git(&["ls-tree", "-r", "-z", base], MAX_TREE)?;
        let original = LocalDeliveryIdentity::digest(&tree, false)?;
        let commit = checkpoints.contains(&"publication.commit");
        if commit && staged == original {
            return Some(Self::refusal(
                "stage the reviewed changes before declaring a post-finish commit",
            ));
        }
        if !commit && staged != original {
            return Some(Self::refusal(
                "declare a local commit before integrating staged changes",
            ));
        }
        let mut targets = Map::new();
        for target in checkpoints
            .iter()
            .filter_map(|name| name.strip_prefix(INTEGRATE))
        {
            let reference = format!("refs/heads/{target}");
            if target == source {
                return Some(Self::refusal(
                    "local integration needs a valid different target branch",
                ));
            }
            match git.run(&["check-ref-format", &reference], 4096)?.0 {
                0 => {}
                1 => {
                    return Some(Self::refusal(
                        "local integration needs a valid different target branch",
                    ))
                }
                _ => return None,
            }
            let Some(head) = git.branch(target)? else {
                return Some(Self::refusal("local integration target must already exist"));
            };
            targets.insert(target.to_owned(), Value::String(head));
        }
        if git.git(&["rev-parse", "HEAD"], 4096)? != base {
            return Some(Self::refusal("HEAD changed while preparing local delivery"));
        }
        let common = git.common_path()?;
        let project = git.project_path()?;
        Some(json!({"proof": {
            "project": project.to_str()?, "common": common.to_str()?, "staged_sha256": staged,
            "commit_declared": commit, "targets": targets,
        }}))
    }

    fn refusal(reason: &str) -> Value {
        json!({"reason": reason})
    }
}
