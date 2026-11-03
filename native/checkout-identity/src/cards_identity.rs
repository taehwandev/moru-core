//! Owner: shared canonical repository identity for one CLI invocation.
//! Allowed: std, sha2 and existing bounded Git/whitespace readers.
//! Forbidden: database access, writes, cross-call memoization or authority.
//! Callers/tests: cards_process/mailbox_status_process; identity and bundle tests.
use crate::{gitrun::GitRead, statusline::Renderer};
use sha2::{Digest, Sha256};
use std::path::Path;

pub(crate) struct CardRepository;

impl CardRepository {
    pub(crate) fn key(project: &Path) -> Option<String> {
        let root = project.to_str()?;
        let identity = GitRead::run(
            root,
            &["rev-parse", "--path-format=absolute", "--git-common-dir"],
        )
        .ok()?;
        let identity = identity
            .as_ref()
            .map(|s| Renderer::strip(s))
            .unwrap_or(root);
        Some(format!("{:x}", Sha256::digest(identity.as_bytes()))[..24].to_owned())
    }
}
