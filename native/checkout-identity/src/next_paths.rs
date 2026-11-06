//! owner: NextPaths; allowed imports: std, libc passwd lookup, DiscoveryFs, Text;
//! forbidden imports: writes, shell, environment mutation; callers/tests: NextProcess;
//! verification: home aliases, named-user expansion, Darwin spelling, evidence stems.
use crate::{discovery_fs::DiscoveryFs, text::Text};
use std::{
    env,
    ffi::{CStr, CString},
    path::{Path, PathBuf},
};

pub(super) struct NextPaths;
impl NextPaths {
    pub(super) fn home() -> Option<PathBuf> {
        Some(PathBuf::from(Text::norm_path(&env::var("HOME").ok()?)))
    }

    pub(super) fn expand(path: &Path, home: &Path) -> Option<PathBuf> {
        let text = path.to_str()?;
        let expanded = if let Some(tail) = text.strip_prefix('~') {
            let (user, suffix) = tail.split_once('/').unwrap_or((tail, ""));
            let base = if user.is_empty() {
                home.to_owned()
            } else {
                Self::user_home(user)?
            };
            // expanduser strips redundant root separators before joining the tail.
            PathBuf::from(format!(
                "{}/{}",
                base.to_str()?.trim_end_matches('/'),
                suffix
            ))
        } else {
            path.to_owned()
        };
        Some(expanded)
    }

    pub(super) fn project(path: &Path, home: &Path) -> Option<PathBuf> {
        let project = Self::existing(&Self::expand(path, home)?)?;
        project.is_dir().then_some(project)
    }

    pub(super) fn existing(path: &Path) -> Option<PathBuf> {
        DiscoveryFs::resolve(path)
    }

    fn user_home(user: &str) -> Option<PathBuf> {
        let user = CString::new(user).ok()?;
        let mut size = 1024;
        loop {
            let mut record: libc::passwd = unsafe { std::mem::zeroed() };
            let mut result = std::ptr::null_mut();
            let mut buffer = vec![0u8; size];
            let code = unsafe {
                libc::getpwnam_r(
                    user.as_ptr(),
                    &mut record,
                    buffer.as_mut_ptr().cast(),
                    buffer.len(),
                    &mut result,
                )
            };
            if code == libc::ERANGE && size < 1024 * 1024 {
                size *= 2;
                continue;
            }
            if code != 0 || result.is_null() || record.pw_dir.is_null() {
                return None;
            }
            let value = unsafe { CStr::from_ptr(record.pw_dir) }.to_str().ok()?;
            // Non-absolute passwd homes have version-dependent pathlib expansion.
            return value.starts_with('/').then(|| PathBuf::from(value));
        }
    }

    pub(super) fn ledger(evidence: &Path) -> Option<PathBuf> {
        let name = evidence.file_name()?.to_str()?;
        let filename = if name == "preflight.json" {
            "gate-evidence.json".to_owned()
        } else {
            let dot = name.rfind('.');
            let split = dot.filter(|i| {
                *i > 0
                    && (*i + 1 < name.len() || env!("MORU_NEXT_TRAILING_DOT_SUFFIX") == "true")
                    && (env!("MORU_NEXT_DOT_PREFIX_PY_SUFFIX") == "true"
                        || name[..*i].chars().any(|c| c != '.'))
            });
            let stem = split.map_or(name, |i| &name[..i]);
            format!("{stem}-gate-evidence.json")
        };
        Some(evidence.parent()?.join(filename))
    }
}
