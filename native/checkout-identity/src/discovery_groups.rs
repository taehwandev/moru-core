//! Owner: workspace-group discovery candidates, without workspace authority.
//! Allowed: serde_json and existing registry, filesystem and candidate readers.
//! Forbidden: scope/launch decisions, writes, services, caches or new processes.
//! Callers/tests: discovery_search; native group tests and transported smoke.
use crate::{
    discovery_candidates::Candidates, discovery_fs::DiscoveryFs as Fs, discovery_registry::Registry,
};
use serde_json::Value;

pub(crate) struct WorkspaceGroups;

impl WorkspaceGroups {
    pub(crate) fn add(registry: &Value, request: &str, candidates: &mut Candidates) -> Option<()> {
        let groups = registry.get("workspace_groups").and_then(Value::as_array);
        for group in groups.into_iter().flatten() {
            let Some(group) = group.as_object() else {
                continue;
            };
            if group.get("disabled") == Some(&Value::Bool(true)) {
                continue;
            }
            let name = group
                .get("name")
                .filter(|v| Registry::truthy(v))
                .or_else(|| group.get("id").filter(|v| Registry::truthy(v)));
            // Python str() for non-string names is deliberately not approximated.
            let name = match name {
                Some(value) => value.as_str()?,
                None => "workspace",
            };
            let mut group_aliases = vec![name.to_owned()];
            Self::aliases(&mut group_aliases, group.get("aliases"));
            let group_match = Self::matches(&group_aliases, request)?;
            for member in group
                .get("members")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let Some(member) = member.as_object() else {
                    continue;
                };
                if member.get("disabled") == Some(&Value::Bool(true)) {
                    continue;
                }
                let Some(path) = Registry::entry_path(member)? else {
                    continue;
                };
                if !Fs::exists(&path)? {
                    continue;
                }
                let Some(root) = Fs::root(&path)? else {
                    continue;
                };
                let mut aliases = Vec::new();
                let role = member
                    .get("role")
                    .filter(|v| Registry::truthy(v))
                    .or_else(|| member.get("name"));
                if let Some(role) = role.and_then(Value::as_str).filter(|s| !s.is_empty()) {
                    aliases.push(role.to_owned());
                }
                let basename = root.file_name().and_then(|s| s.to_str()).unwrap_or("");
                if !aliases.iter().any(|v| v == basename) {
                    aliases.push(basename.to_owned());
                }
                Self::aliases(&mut aliases, member.get("aliases"));
                let member_match = Self::matches(&aliases, request)?;
                if !group_match && !member_match {
                    continue;
                }
                let mut combined = group_aliases.clone();
                for alias in aliases {
                    if !combined.contains(&alias) {
                        combined.push(alias);
                    }
                }
                let (files, markers) = Fs::facts(&root)?;
                candidates.add(
                    root,
                    files,
                    markers,
                    if member_match { 120 } else { 35 },
                    if member_match {
                        "workspace group member alias matched request"
                    } else {
                        "workspace group alias matched request"
                    },
                    "workspace_group",
                    &combined,
                )?;
            }
        }
        Some(())
    }

    fn aliases(aliases: &mut Vec<String>, value: Option<&Value>) {
        for alias in value.and_then(Value::as_array).into_iter().flatten() {
            if let Some(alias) = alias.as_str() {
                if !aliases.iter().any(|v| v == alias) {
                    aliases.push(alias.to_owned());
                }
            }
        }
    }

    fn matches(aliases: &[String], request: &str) -> Option<bool> {
        for alias in aliases {
            if Candidates::matches(alias, request, true)? {
                return Some(true);
            }
        }
        Some(false)
    }
}
