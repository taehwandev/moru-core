//! owner: VerificationGit; allowed imports: bounded capture, std, text normalization;
//! forbidden imports: writes, arbitrary Git commands; callers/tests: Verification;
//! verification: exact argv, stdin, nonzero exit and both-pipe decoding parity.
use crate::{read_process::capture_raw, text::Text};
use std::{path::Path, process::Command, time::Duration};
pub(super) struct VerificationGit;
impl VerificationGit {
    pub(super) fn status(project: &Path) -> Option<String> {
        if !crate::python_encoding::PythonEncoding::utf8() {
            return None;
        }
        let (stdout, stderr, success) = capture_raw(
            Command::new("git")
                .args(["status", "--porcelain", "--untracked-files=all"])
                .current_dir(project),
            Duration::from_secs(10),
        )
        .ok()??;
        Self::decode(&stdout, &stderr, success)
    }
    fn decode(stdout: &[u8], stderr: &[u8], success: bool) -> Option<String> {
        // subprocess text=True decodes both streams before inspecting returncode.
        let stdout = std::str::from_utf8(stdout).ok()?;
        std::str::from_utf8(stderr).ok()?;
        Some(if success {
            Text::universal_newlines(stdout)
        } else {
            String::new()
        })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn decode_precedes_nonzero_exit_and_translates_newlines() {
        assert_eq!(
            VerificationGit::decode(b"?? a.py\r\n", b"", true),
            Some("?? a.py\n".into())
        );
        assert_eq!(
            VerificationGit::decode(b"ignored", b"failure", false),
            Some(String::new())
        );
        assert_eq!(VerificationGit::decode(b"\xff", b"", false), None);
        assert_eq!(VerificationGit::decode(b"ignored", b"\xff", false), None);
    }
}
