//! owner: legacy claim filename derivation and validation.
//! allowed imports: the SHA-1 digest and filename primitives only.
//! forbidden imports: authentication, authority, filesystem writes and network.
//! callers/tests: claim creation, renewal and release; test_path_claims.
//! verification: exact parity with hashlib on normalized UTF-8 paths.
use sha1::{Digest, Sha1};
use std::ffi::CString;

pub(super) struct PathClaimFilename;

impl PathClaimFilename {
    pub(super) fn derive(path: &str) -> Option<CString> {
        // SHA-1 is the existing on-disk lookup key for advisory claims.
        let digest = Sha1::digest(path.as_bytes());
        CString::new(format!("{digest:x}.json")).ok()
    }

    pub(super) fn legacy(name: &str) -> Option<CString> {
        let hash = name.strip_suffix(".json")?;
        if hash.len() != 40
            || !hash
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return None;
        }
        CString::new(name).ok()
    }
}
