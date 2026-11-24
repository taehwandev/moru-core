//! owner: project-relative live-web path normalization and claim argument ordering.
//! allowed imports: read-only filesystem resolution and path helpers.
//! forbidden imports: writes, claim ownership policy and network.
//! callers/tests: path_claims claim/release and live-web edit routes.
//! verification: symlinks, missing components, containment and stable deduplication.
use crate::{discovery_fs::DiscoveryFs, text::Text};
use serde_json::{json, Value};
use std::{collections::BTreeSet, path::Path};

pub(super) struct ProjectRelativePath;

impl ProjectRelativePath {
    pub(super) fn claim_arguments(input: &Value) -> Option<Value> {
        let project = Path::new(input.get("project")?.as_str()?);
        if !project.is_absolute() {
            return None;
        }
        let mut paths = BTreeSet::new();
        for raw in input.get("paths")?.as_array()? {
            let raw = raw.as_str()?;
            let Some(relative) = Self::resolve(project, raw)? else {
                return Some(json!({"outside": raw}));
            };
            paths.insert(relative);
        }
        Some(json!({"paths": paths}))
    }

    // Outer None is unsupported resolution, inner None is a known outside path.
    pub(super) fn resolve(project: &Path, raw: &str) -> Option<Option<String>> {
        let path = if raw.starts_with('~') {
            DiscoveryFs::expand(Path::new(&Text::norm_path(raw)))?
        } else {
            Path::new(raw).to_owned()
        };
        let resolved = DiscoveryFs::resolve_allow_missing(&project.join(path))?;
        let Ok(relative) = resolved.strip_prefix(project) else {
            return Some(None);
        };
        let relative = relative.to_str()?;
        Some(Some(
            if relative.is_empty() { "." } else { relative }.into(),
        ))
    }
}
