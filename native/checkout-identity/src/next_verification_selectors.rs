//! owner: VerificationSelectors; allowed imports: std metadata/path;
//! forbidden imports: git, writes, subprocess; callers/tests: Verification, NextAdvice, NextProcess;
//! verification: directory-relative selector eligibility and POSIX quoting parity.
use std::path::Path;

const MAX_SELECTOR_LENGTH: usize = 240;

pub(crate) struct VerificationSelectors;

impl VerificationSelectors {
    pub(crate) fn sh_quote(s: &str) -> String {
        if s.is_empty() {
            return "''".to_owned();
        }
        if s.bytes().all(|b| {
            b.is_ascii_alphanumeric()
                || matches!(
                    b,
                    b'_' | b'@' | b'%' | b'+' | b'=' | b':' | b',' | b'.' | b'/' | b'-'
                )
        }) {
            s.to_owned()
        } else {
            format!("'{}'", s.replace('\'', "'\"'\"'"))
        }
    }

    pub(crate) fn compile_arg_quote(rel_posix: &str) -> String {
        if rel_posix.starts_with('-') {
            Self::sh_quote(&format!("./{rel_posix}"))
        } else {
            Self::sh_quote(rel_posix)
        }
    }

    fn ascii_identifier(part: &str) -> Option<bool> {
        if !part.is_ascii() {
            return None;
        }
        let mut bytes = part.bytes();
        let first = bytes.next()?;
        if !(first.is_ascii_alphabetic() || first == b'_') {
            return Some(false);
        }
        Some(bytes.all(|b| b.is_ascii_alphanumeric() || b == b'_'))
    }

    pub(crate) fn path_exists_lstat(path: &Path) -> Option<bool> {
        if path.to_str()?.contains('\0') {
            return Some(false);
        }
        match std::fs::symlink_metadata(path) {
            Ok(_) => Some(true),
            Err(error)
                if matches!(
                    error.raw_os_error(),
                    Some(libc::ENOENT) | Some(libc::ENOTDIR) | Some(libc::EBADF)
                ) =>
            {
                Some(false)
            }
            Err(_) => None,
        }
    }

    pub(crate) fn selector_eligibility(
        tests_dir: &Path,
        rel_under_tests: &[&str],
        reference_is_file: fn(&Path) -> Option<bool>,
    ) -> Option<Result<String, &'static str>> {
        let last = rel_under_tests.last()?;
        let stem = last.strip_suffix(".py")?;
        let mut parts: Vec<&str> = rel_under_tests[..rel_under_tests.len() - 1].to_vec();
        parts.push(stem);
        let selector = parts.join(".");
        if selector.len() > MAX_SELECTOR_LENGTH {
            return Some(Err("invalid_selector_identifier"));
        }
        for part in &parts {
            if !Self::ascii_identifier(part)? {
                return Some(Err("invalid_selector_identifier"));
            }
        }
        let Ok(resolved_tests) = std::fs::canonicalize(tests_dir) else {
            return Some(Err("missing_or_deleted"));
        };
        if !tests_dir.is_dir() {
            return Some(Err("missing_or_deleted"));
        }
        let mut candidate = tests_dir.to_path_buf();
        for part in rel_under_tests {
            candidate.push(part);
        }
        if !Self::path_exists_lstat(&candidate)? {
            return Some(Err("missing_or_deleted"));
        }
        if !reference_is_file(&candidate)? {
            return Some(Err("escapes_test_directory"));
        }
        let Ok(resolved_cand) = std::fs::canonicalize(&candidate) else {
            return Some(Err("escapes_test_directory"));
        };
        if !resolved_cand.starts_with(&resolved_tests) {
            return Some(Err("escapes_test_directory"));
        }
        for end in 1..parts.len() {
            let mut prefix = tests_dir.to_path_buf();
            for part in &parts[..end] {
                prefix.push(part);
            }
            if prefix.exists() {
                let Ok(resolved_prefix) = std::fs::canonicalize(&prefix) else {
                    return Some(Err("escapes_test_directory"));
                };
                if !resolved_prefix.starts_with(&resolved_tests) {
                    return Some(Err("escapes_test_directory"));
                }
            }
            let mut mod_py = prefix;
            mod_py.set_extension("py");
            if Self::path_exists_lstat(&mod_py)? {
                return Some(Err("ambiguous_module_package"));
            }
        }
        Some(Ok(selector))
    }
}
