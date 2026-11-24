//! owner: bounded source reads and path facts for structural review.
//! allowed imports: read-only filesystem access, UTF-8, supplied path rules and JSON.
//! forbidden imports: writes, Git execution and review outcomes.
//! callers/tests: structural review through the private completion protocol.
//! verification: compare with Python UTF-8 universal newlines and splitlines.
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::{
    fs::{self, File},
    io::Read,
    path::{Component, Path},
};

pub(super) struct StructureSourceRead;

struct TestPathRules<'a> {
    parts: Vec<&'a str>,
    prefixes: Vec<&'a str>,
    suffixes: Vec<&'a str>,
    case_suffixes: Vec<&'a str>,
}

impl TestPathRules<'_> {
    fn matches(&self, path: &Path, stem: &str) -> Option<bool> {
        if !stem.is_ascii() || !path.to_str()?.is_ascii() {
            return None;
        }
        let lower_stem = stem.to_ascii_lowercase();
        Some(
            path.components().any(|part| {
                part.as_os_str().to_str().is_some_and(|name| {
                    self.parts
                        .iter()
                        .any(|probe| name.eq_ignore_ascii_case(probe))
                })
            }) || self
                .prefixes
                .iter()
                .any(|prefix| lower_stem.starts_with(*prefix))
                || self
                    .suffixes
                    .iter()
                    .any(|suffix| lower_stem.ends_with(*suffix))
                || self
                    .case_suffixes
                    .iter()
                    .any(|suffix| stem.ends_with(*suffix)),
        )
    }
}

impl StructureSourceRead {
    pub(super) fn batch(payload: &Value) -> Option<Value> {
        let source = Path::new(payload.get("source")?.as_str()?);
        if !source.is_absolute() || source.canonicalize().ok()? != source || !source.is_dir() {
            return None;
        }
        let paths = payload.get("paths")?.as_array()?;
        if paths.len() > 256 {
            return None;
        }
        let policy = payload.get("test_policy")?;
        let read_rule = |key| -> Option<Vec<&str>> {
            policy
                .get(key)?
                .as_array()?
                .iter()
                .map(Value::as_str)
                .collect()
        };
        let test_rules = TestPathRules {
            parts: read_rule("parts")?,
            prefixes: read_rule("prefixes")?,
            suffixes: read_rule("suffixes")?,
            case_suffixes: read_rule("case_suffixes")?,
        };
        // Leave room for worst-case JSON control-character escaping.
        let mut remaining = 128 * 1024;
        let mut rows = Vec::with_capacity(paths.len());
        for entry in paths {
            let name = entry.get(0)?.as_str()?;
            let stem = entry.get(1)?.as_str()?;
            let relative = Path::new(name);
            if name.is_empty()
                || name.contains('\0')
                || !relative
                    .components()
                    .all(|part| matches!(part, Component::Normal(_)))
            {
                rows.push((None, None));
                continue;
            }
            rows.push((
                Self::read(source, relative, &mut remaining),
                test_rules.matches(relative, stem),
            ));
        }
        Some(json!({ "rows": rows }))
    }

    pub(super) fn read(source: &Path, relative: &Path, remaining: &mut u64) -> Option<Value> {
        let path = source.join(relative);
        let metadata = fs::metadata(&path).ok()?;
        if !metadata.is_file() || metadata.len() > *remaining {
            return None;
        }
        let mut bytes = Vec::new();
        let result = File::open(path)
            .ok()?
            .take(*remaining + 1)
            .read_to_end(&mut bytes);
        let size = bytes.len() as u64;
        let budget = *remaining;
        *remaining = remaining.saturating_sub(size);
        if result.is_err() || size > budget {
            return None;
        }
        Some(match std::str::from_utf8(&bytes) {
            Ok(text) => json!(PythonText::splitlines(text)),
            Err(_) => Value::Bool(false),
        })
    }
}
