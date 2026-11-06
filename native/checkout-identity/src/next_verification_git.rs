//! owner: VerificationGit; allowed imports: bounded capture, std, text normalization;
//! forbidden imports: writes, arbitrary Git commands; callers/tests: Verification;
//! verification: exact argv, stdin, nonzero exit and both-pipe decoding parity.
use crate::{read_process::capture_raw, text::Text};
use std::{env, path::Path, process::Command, time::Duration};
// macOS SDK xlocale/_langinfo.h; libc exposes this symbol only on Linux.
extern "C" {
    fn nl_langinfo_l(item: libc::nl_item, locale: libc::locale_t) -> *mut libc::c_char;
}
pub(super) struct VerificationGit;
impl VerificationGit {
    pub(super) fn status(project: &Path) -> Option<String> {
        if !Self::utf8() {
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
    fn utf8() -> bool {
        match env::var("PYTHONUTF8") {
            Ok(value) => return value == "1",
            Err(env::VarError::NotUnicode(_)) => return false,
            Err(env::VarError::NotPresent) => {}
        }
        if env!("MORU_NEXT_C_LOCALE_UTF8") != "true" {
            return false;
        }
        let mut locale = String::new();
        for name in ["LC_ALL", "LC_CTYPE", "LANG"] {
            match env::var(name) {
                Ok(value) if !value.is_empty() => {
                    locale = value;
                    break;
                }
                Err(env::VarError::NotUnicode(_)) => return false,
                _ => {}
            }
        }
        if matches!(locale.as_str(), "" | "C" | "POSIX") {
            return true;
        }
        if !Self::utf8_locale(&locale) {
            return false;
        }
        let Ok(name) = std::ffi::CString::new(locale) else {
            return false;
        };
        // Per-locale APIs avoid mutating process-global locale or trusting suffix alone.
        unsafe {
            let handle = libc::newlocale(libc::LC_CTYPE_MASK, name.as_ptr(), std::ptr::null_mut());
            if handle.is_null() {
                return false;
            }
            let codeset = nl_langinfo_l(libc::CODESET, handle);
            let supported = !codeset.is_null()
                && std::ffi::CStr::from_ptr(codeset)
                    .to_bytes()
                    .eq_ignore_ascii_case(b"UTF-8");
            libc::freelocale(handle);
            supported
        }
    }
    fn utf8_locale(locale: &str) -> bool {
        let locale = locale.to_ascii_lowercase();
        let locale = locale.split('@').next().unwrap_or("");
        matches!(locale, "" | "c" | "posix")
            || locale.ends_with(".utf-8")
            || locale.ends_with(".utf8")
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
    #[test]
    fn locale_proof_is_bounded_and_does_not_assume_latin1() {
        for locale in [
            "",
            "C",
            "POSIX",
            "C.UTF-8",
            "en_US.utf8",
            "ko_KR.UTF-8@modifier",
        ] {
            assert!(VerificationGit::utf8_locale(locale));
        }
        for locale in ["en_US", "en_US.ISO8859-1", "unknown", "UTF8"] {
            assert!(!VerificationGit::utf8_locale(locale));
        }
    }
}
