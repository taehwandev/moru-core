//! Existing RegistryRead owner: bounded metadata-only evidence identities.
//! Allowed: std filesystem/Unix metadata and JSON; forbidden: file contents,
//! writes, deletion, locks or authority decisions. Callers/tests: retention
//! identity probe; original-source and changed-evidence revalidation tests.
use super::RegistryRead;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
};

impl RegistryRead {
    pub(super) fn retention_identities(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        let roots = object.get("paths")?.as_array()?;
        if object.len() != 1 || roots.len() > 256 {
            return None;
        }
        let mut remaining = 4096;
        let mut results = Vec::with_capacity(roots.len());
        for root in roots {
            results.push(Self::identity_rows(
                Path::new(root.as_str()?),
                &mut remaining,
            )?);
        }
        Some(Value::Array(results))
    }

    fn identity_rows(root: &Path, remaining: &mut usize) -> Option<Value> {
        if !root.is_absolute() || root.canonicalize().ok()?.as_path() != root || *remaining == 0 {
            return None;
        }
        let paths = Self::identity_paths(root, *remaining - 1)?;
        *remaining -= paths.len();
        let mut result = Vec::with_capacity(paths.len());
        // Match Python: collect/sort every path before reading any returned stat.
        for path in paths {
            let metadata = fs::symlink_metadata(&path).ok()?;
            let relative = if path == root {
                "."
            } else {
                path.strip_prefix(root).ok()?.to_str()?
            };
            let modified = i64::try_from(
                metadata.mtime() as i128 * 1_000_000_000 + metadata.mtime_nsec() as i128,
            )
            .ok()?;
            let changed = i64::try_from(
                metadata.ctime() as i128 * 1_000_000_000 + metadata.ctime_nsec() as i128,
            )
            .ok()?;
            if metadata.size() > i64::MAX as u64 {
                return None;
            }
            result.push(json!([
                relative,
                metadata.dev(),
                metadata.ino(),
                metadata.mode(),
                metadata.size(),
                modified,
                changed
            ]));
        }
        Some(Value::Array(result))
    }

    fn identity_paths(root: &Path, limit: usize) -> Option<Vec<PathBuf>> {
        let metadata = fs::symlink_metadata(root).ok()?;
        if metadata.file_type().is_symlink() {
            return None;
        }
        let mut directories = if metadata.is_dir() {
            vec![root.to_owned()]
        } else {
            vec![]
        };
        let mut children = Vec::new();
        while let Some(directory) = directories.pop() {
            let kind = fs::symlink_metadata(&directory).ok()?.file_type();
            if !kind.is_dir() || kind.is_symlink() {
                return None;
            }
            for entry in fs::read_dir(directory).ok()? {
                let entry = entry.ok()?;
                let path = entry.path();
                path.to_str()?;
                if entry.file_type().ok()?.is_dir() {
                    directories.push(path.clone());
                }
                children.push(path);
                if children.len() > limit {
                    return None;
                }
            }
        }
        children.sort();
        let mut paths = vec![root.to_owned()];
        paths.extend(children);
        Some(paths)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let root = std::env::temp_dir().join(format!(
                "moru-identity-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&root).unwrap();
            Self(root.canonicalize().unwrap())
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    #[test]
    fn global_path_order_includes_hidden_names_and_starts_with_root() {
        let f = Fixture::new();
        fs::create_dir(f.0.join("z")).unwrap();
        fs::write(f.0.join("z/a"), b"x").unwrap();
        fs::write(f.0.join("z-b"), b"").unwrap();
        fs::write(f.0.join(".hidden"), b"").unwrap();
        fs::write(f.0.join("한글"), b"").unwrap();
        let value = RegistryRead::retention_identities(&json!({"paths":[f.0]})).unwrap();
        let names: Vec<_> = value[0]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row[0].as_str().unwrap())
            .collect();
        assert_eq!(names, vec![".", ".hidden", "z", "z/a", "z-b", "한글"]);
        assert!(value[0]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row.as_array().unwrap().len() == 7));
    }
    #[test]
    fn directory_symlinks_are_recorded_without_descending_and_bound_has_no_partial_result() {
        use std::os::unix::fs::symlink;
        let f = Fixture::new();
        fs::create_dir(f.0.join("nested")).unwrap();
        fs::write(f.0.join("nested/child"), b"").unwrap();
        symlink("nested", f.0.join("link")).unwrap();
        symlink("absent", f.0.join("broken")).unwrap();
        assert_eq!(RegistryRead::identity_paths(&f.0, 4).unwrap().len(), 5);
        assert!(RegistryRead::identity_paths(&f.0, 3).is_none());
        assert!(RegistryRead::retention_identities(&json!({"paths":[f.0.join("link")]})).is_none());
    }
    #[test]
    fn a_failed_batch_never_returns_partial_root_identities() {
        let f = Fixture::new();
        assert!(
            RegistryRead::retention_identities(&json!({"paths":[f.0,f.0.join("absent")]}))
                .is_none()
        );
        assert_eq!(
            RegistryRead::retention_identities(&json!({"paths":[]})),
            Some(json!([]))
        );
    }
}
