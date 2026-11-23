//! owner: cross-file addition and copy findings for structural review.
//! allowed imports: JSON and formatting.
//! forbidden imports: filesystem, Git execution and authority.
//! callers/tests: structural diagnostic batch and exact Python parity fixtures.
//! verification: strict path order, pressure threshold and copy disclosure.
use serde_json::{json, Value};

pub(super) struct StructureSourceLayout;

impl StructureSourceLayout {
    pub(super) fn findings(input: &Value) -> Option<Value> {
        let limit = input.get("limit")?.as_u64()?;
        let paths = input.get("paths")?.as_array()?;
        if paths.len() > 4096 {
            return None;
        }
        let mut added = Vec::new();
        let mut copied = Vec::new();
        for entry in paths {
            let path = entry.get(0)?.as_str()?;
            match entry.get(1)?.as_str() {
                Some("A") => added.push(path),
                Some("C") => copied.push(path),
                Some(_) => {}
                None if entry.get(1)?.is_null() => {}
                None => return None,
            }
        }
        let mut warnings = Vec::new();
        if u64::try_from(added.len()).ok()? > limit {
            let shown = Self::shown(&added);
            warnings.push(format!(
                "change adds {} new development source files ({shown}); \
                 new-file review-pressure limit is {limit}; \
                 structure-review evidence must justify each new file or abstraction against a \
                 concrete present risk (see Match Structure To The Problem), or the change should \
                 be collapsed into fewer files",
                added.len()
            ));
        }
        if !copied.is_empty() {
            let shown = Self::shown(&copied);
            warnings.push(format!(
                "change adds {} content-preserving source copy/copies ({shown}); \
                 structure-review evidence must name the copy-first source and target, the \
                 behavior-parity verification, and the caller-cutover or legacy-removal condition",
                copied.len()
            ));
        }
        Some(json!({"added": added.len(), "copied": copied.len(), "warnings": warnings}))
    }

    fn shown(paths: &[&str]) -> String {
        let mut summary = paths[..paths.len().min(8)].join(", ");
        if paths.len() > 8 {
            summary.push_str("; ...");
        }
        summary
    }
}
