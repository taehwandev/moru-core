//! owner: ManifestIo; allowed imports: std, sha2, serde_json, validation;
//! forbidden imports: Python/runtime launchers; callers/tests: ReactManifest; verification: fixture parity.
use super::validation::ManifestValidation as V;
use super::value::ManifestValue as Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, path::Path};
pub struct ManifestIo;
impl ManifestIo {
    pub fn sources(root: &Path) -> Option<BTreeMap<String, String>> {
        let mut found = BTreeMap::new();
        if !root.is_dir() {
            return Some(found);
        }
        Self::walk(root, root, &mut found)?;
        Some(found)
    }
    fn walk(root: &Path, dir: &Path, found: &mut BTreeMap<String, String>) -> Option<()> {
        let entries = match fs::read_dir(dir) {
            Ok(v) => v,
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::PermissionDenied | std::io::ErrorKind::NotFound
                ) =>
            {
                return Some(())
            }
            Err(_) => return None,
        };
        for item in entries {
            let item = item.ok()?;
            let path = item.path();
            let kind = item.file_type().ok()?;
            if item.file_name() == "SKILL.md" {
                let name = path
                    .strip_prefix(root)
                    .ok()?
                    .to_str()?
                    .replace(std::path::MAIN_SEPARATOR, "/");
                found.insert(name, format!("{:x}", Sha256::digest(fs::read(&path).ok()?)));
            }
            if kind.is_dir() {
                Self::walk(root, &path, found)?;
            }
        }
        Some(())
    }
    pub fn source_failures(payload: &Value, root: &Path) -> Option<Vec<String>> {
        let entries = payload.get("skills")?.as_array()?;
        let mut expected = BTreeMap::new();
        for e in entries.iter().filter_map(Value::as_object) {
            expected.insert(V::string(e.get("path")?)?, V::string(e.get("sha256")?)?);
        }
        let actual = Self::sources(root)?;
        let mut failures = Vec::new();
        failures.extend(
            expected
                .keys()
                .filter(|k| !actual.contains_key(*k))
                .map(|k| format!("missing source skill: {k}")),
        );
        failures.extend(
            actual
                .keys()
                .filter(|k| !expected.contains_key(*k))
                .map(|k| format!("unexpected source skill: {k}")),
        );
        failures.extend(
            expected
                .iter()
                .filter(|(k, v)| actual.get(*k).is_some_and(|a| a != *v))
                .map(|(k, _)| format!("source skill hash changed: {k}")),
        );
        Some(failures)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    macro_rules! json { ($($t:tt)*) => { Value::from(serde_json::json!($($t)*)) }; }
    #[test]
    fn missing_root_has_no_sources() {
        assert!(
            ManifestIo::sources(Path::new("/moru-nonexistent-fixture-root-72"))
                .unwrap()
                .is_empty()
        );
    }
    #[test]
    fn source_hashes_and_ordered_differences() {
        let root = std::env::temp_dir().join(format!(
            "moru-react-sources-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(root.join("changed")).unwrap();
        fs::create_dir_all(root.join("extra")).unwrap();
        fs::write(root.join("changed/SKILL.md"), b"abc").unwrap();
        fs::write(root.join("extra/SKILL.md"), b"extra").unwrap();
        let actual = ManifestIo::sources(&root).unwrap();
        assert_eq!(
            actual["changed/SKILL.md"],
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let payload = json!({"skills":[{"path":"missing/SKILL.md","sha256":"bad"},{"path":"changed/SKILL.md","sha256":"bad"}]});
        assert_eq!(
            ManifestIo::source_failures(&payload, &root).unwrap(),
            vec![
                "missing source skill: missing/SKILL.md",
                "unexpected source skill: extra/SKILL.md",
                "source skill hash changed: changed/SKILL.md"
            ]
        );
        fs::remove_dir_all(root).unwrap();
    }
}
