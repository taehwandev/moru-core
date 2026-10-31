//! Checkout identity lookup served over a line-delimited JSON protocol.

mod framing;
mod gitrun;
mod identity;
mod metadata_text;
mod protocol;
mod text;

use std::io::{self, BufRead, Write};

/// Entry points for resolving a checkout identity and serving the NDJSON protocol.
pub struct CheckoutIdentity;

impl CheckoutIdentity {
    /// Resolve `(common_dir, branch)` for the checkout at `root`.
    pub fn lookup(root: &str) -> Result<(Option<String>, String), ()> {
        identity::identity(root)
    }

    /// Answer one response line per request line until the reader reaches EOF.
    pub fn serve<R: BufRead, W: Write>(reader: R, writer: W) -> io::Result<()> {
        protocol::Protocol::serve(reader, writer)
    }
}
