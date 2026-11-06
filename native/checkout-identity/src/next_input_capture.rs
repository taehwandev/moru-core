//! owner: InputCapture; allowed imports: read-only fs, raw GitRead, sha2, serde_json quoting;
//! forbidden imports: state writes, command execution beyond Git listing; callers: InputFreshness;
//! verification: Python input digest golden fixtures, limits, symlink and metadata cases.
use crate::gitrun::GitRead;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    fs,
    io::Read,
    os::unix::fs::MetadataExt,
    path::{Component, Path, PathBuf},
};
pub(super) struct InputCapture;
impl InputCapture {
    /// Outer None declines uncertain semantics; inner None is Python's capture exception.
    pub fn capture(root: &Path, paths: &[String]) -> Option<Option<String>> {
        Self::bounded(root, paths, 5000, 256 * 1024 * 1024)
    }
    fn bounded(
        root: &Path,
        paths: &[String],
        max_files: usize,
        max_bytes: u64,
    ) -> Option<Option<String>> {
        if paths.len() > max_files || paths.iter().any(String::is_empty) {
            return Some(None);
        }
        let selected = if paths.is_empty() {
            match GitRead::input_paths(root)? {
                Ok(text) => text
                    .split('\0')
                    .filter(|s| !s.is_empty())
                    .map(str::to_owned)
                    .collect::<BTreeSet<_>>(),
                Err(()) => return Some(None),
            }
        } else {
            paths.iter().cloned().collect()
        };
        if selected.len() > max_files {
            return Some(None);
        }
        let mut digest = Sha256::new();
        let mut total = 0;
        for relative in selected {
            let Some(record) =
                Self::entry(root, &relative, !paths.is_empty(), &mut total, max_bytes)?
            else {
                return Some(None);
            };
            digest.update(record.as_bytes());
        }
        Some(Some(format!("{:x}", digest.finalize())))
    }
    fn entry(
        root: &Path,
        relative: &str,
        explicit: bool,
        total: &mut u64,
        max_bytes: u64,
    ) -> Option<Option<String>> {
        let rel = Path::new(relative);
        if rel.is_absolute()
            || rel
                .components()
                .any(|c| c == Component::ParentDir || c == Component::Normal(".git".as_ref()))
        {
            return Some(None);
        }
        let path = root.join(rel).components().collect::<PathBuf>();
        match fs::symlink_metadata(&path) {
            Ok(meta) if meta.file_type().is_symlink() => {
                let target = match fs::read_link(&path) {
                    Ok(v) => v,
                    Err(_) => return Some(None),
                };
                let target = target.to_str()?;
                return Some(Some(format!(
                    "[{}, \"symlink\", {}]",
                    Self::quote(relative),
                    Self::quote(target)
                )));
            }
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Some(None),
        }
        if root.to_str()?.starts_with("//") {
            return Some(None);
        }
        let Some(resolved) = Self::resolve(&path)? else {
            return Some(None);
        };
        if resolved != path || !path.starts_with(root) {
            return Some(None);
        }
        let before = match fs::metadata(&path) {
            Ok(meta) => meta,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                return Some(Some(if explicit {
                    format!("[{}, \"missing\"]", Self::quote(relative))
                } else {
                    String::new()
                }))
            }
            Err(_) => return Some(None),
        };
        if !before.is_file() {
            return Some(None);
        }
        *total = match total.checked_add(before.len()) {
            Some(v) => v,
            None => return Some(None),
        };
        if *total > max_bytes {
            return Some(None);
        }
        let mut file = match fs::File::open(&path) {
            Ok(v) => v,
            Err(_) => return Some(None),
        };
        let mut contents = Sha256::new();
        let mut buffer = vec![0u8; 1024 * 1024];
        loop {
            match file.read(&mut buffer) {
                Ok(0) => break,
                Ok(count) => contents.update(&buffer[..count]),
                Err(_) => return Some(None),
            }
        }
        let after = match fs::metadata(&path) {
            Ok(v) => v,
            Err(_) => return Some(None),
        };
        if Self::stamp(&before) != Self::stamp(&after) {
            return Some(None);
        }
        Some(Some(format!(
            "[{}, {}, \"{:x}\"]",
            Self::quote(relative),
            before.mode() & 0o7777,
            contents.finalize()
        )))
    }
    fn stamp(meta: &fs::Metadata) -> (u64, u64, u32, u64, i64, i64, i64, i64) {
        (
            meta.dev(),
            meta.ino(),
            meta.mode(),
            meta.len(),
            meta.mtime(),
            meta.mtime_nsec(),
            meta.ctime(),
            meta.ctime_nsec(),
        )
    }
    fn resolve(path: &Path) -> Option<Option<PathBuf>> {
        let mut missing = Vec::new();
        let mut current = path.to_owned();
        loop {
            match current.canonicalize() {
                Ok(mut resolved) => {
                    for name in missing.iter().rev() {
                        resolved.push(name);
                    }
                    return Some(Some(resolved));
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    // A dangling parent link requires non-strict symlink resolution, not lexical joining.
                    if fs::symlink_metadata(&current).is_ok_and(|m| m.file_type().is_symlink()) {
                        return None;
                    }
                    let Some(name) = current.file_name() else {
                        return Some(None);
                    };
                    missing.push(name.to_owned());
                    let Some(parent) = current.parent() else {
                        return Some(None);
                    };
                    current = parent.to_owned();
                }
                Err(_) => return Some(None),
            }
        }
    }
    fn quote(text: &str) -> String {
        let quoted = serde_json::to_string(text).unwrap();
        let mut out = String::new();
        for c in quoted.chars() {
            if c as u32 >= 127 {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            } else {
                out.push(c);
            }
        }
        out
    }
}
#[cfg(test)]
#[path = "next_input_capture_tests.rs"]
mod tests;
