//! Checkout identity lookup served over a line-delimited JSON protocol.

mod framing;
mod gitrun;
mod read_process;
mod identity;
mod metadata_text;
mod protocol;
mod text;

use std::io::{self, BufRead, Write};

/// Entry points for resolving a checkout identity and serving the NDJSON protocol.
pub struct CheckoutIdentity;

impl CheckoutIdentity {
    /// Exact Python repository-key identity, without metadata shortcuts/cache.
    pub fn repository_key(root: &str) -> Option<String> {
        use sha2::{Digest, Sha256};
        let output = gitrun::GitRead::run(
            root,
            &["rev-parse", "--path-format=absolute", "--git-common-dir"],
        )
        .ok()?;
        let identity = output.as_deref().map(text::Text::py_strip).unwrap_or(root);
        Some(format!("{:x}", Sha256::digest(identity.as_bytes()))[..24].to_owned())
    }

    /// Resolve `(common_dir, branch)` for the checkout at `root`.
    pub fn lookup(root: &str) -> Result<(Option<String>, String), ()> {
        identity::identity(root)
    }

    /// Answer one response line per request line until the reader reaches EOF.
    pub fn serve<R: BufRead, W: Write>(reader: R, writer: W) -> io::Result<()> {
        protocol::Protocol::serve(reader, writer)
    }
}
