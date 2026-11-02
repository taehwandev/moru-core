//! Owner: read-only project registry paths and registered candidate projection.
//! Allowed: std, serde_json, discovery_fs/candidates, existing whitespace renderer.
//! Forbidden: state writes, workspace-group/launch authority, services or caches.
//! Callers/tests: discovery_search; test_native_project_registry and bundle smoke.
use crate::{discovery_candidates::Candidates, discovery_fs::DiscoveryFs as Fs};
use serde_json::{json, Value};
use std::{
    env, fs,
    path::{Path, PathBuf},
};

pub(crate) struct Registry;

impl Registry {
    pub(crate) fn load(registry: Option<&Path>, snapshot: Option<&Value>) -> Option<Value> {
        if let Some(value) = snapshot {
            return Some(value.clone());
        }
        let path = match registry {
            Some(path) => python_path(path),
            None => match env::var("MORU_PROJECT_REGISTRY") {
                Ok(raw) if !raw.is_empty() => Self::path(&raw)?,
                _ => {
                    let state = env::var("MORU_STATE_HOME")
                        .ok()
                        .map(|v| crate::statusline::Renderer::strip(&v).to_owned())
                        .filter(|v| !v.is_empty());
                    let home = PathBuf::from(env::var_os("HOME")?).join(".moru");
                    Fs::expand(&state.map_or(home, PathBuf::from))?.join("projects.json")
                }
            },
        };
        if Fs::exists(&path)? {
            serde_json::from_str(&fs::read_to_string(path).ok()?).ok()
        } else {
            Some(json!({}))
        }
    }

    pub(crate) fn roots(registered: &Value) -> Option<Vec<PathBuf>> {
        let mut roots = Vec::new();
        if let Some(map) = registered.as_object() {
            if map
                .get("workspace_groups")
                .and_then(Value::as_array)
                .is_some_and(|v| !v.is_empty())
            {
                return None;
            }
            if let Some(paths) = map.get("search_roots").and_then(Value::as_array) {
                for path in paths.iter().filter_map(Value::as_str) {
                    roots.push(Self::path(path)?);
                }
            }
        }
        Some(roots)
    }

    pub(crate) fn add_projects(
        registered: &Value,
        request: &str,
        candidates: &mut Candidates,
    ) -> Option<()> {
        let entries = registered
            .as_array()
            .or_else(|| registered.get("projects").and_then(Value::as_array));
        for entry in entries.into_iter().flatten() {
            let Some(map) = entry.as_object() else {
                continue;
            };
            if map.get("disabled") == Some(&Value::Bool(true)) {
                continue;
            }
            let raw = map
                .get("root")
                .filter(|v| truthy(v))
                .or_else(|| map.get("path"));
            let Some(raw) = raw.and_then(Value::as_str).filter(|s| !s.is_empty()) else {
                continue;
            };
            let path = Self::path(raw)?;
            if !Fs::exists(&path)? {
                continue;
            }
            let Some(root) = Fs::root(&path)? else {
                continue;
            };
            let aliases: Vec<String> = match map.get("aliases") {
                None => Vec::new(),
                Some(Value::Array(items)) => items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::to_owned)
                    .collect(),
                _ => return None, // Preserve Python's uncommon iterable/error semantics.
            };
            let mut matched = false;
            for alias in &aliases {
                matched |= Candidates::matches(alias, request, true)?;
            }
            if matched
                || Candidates::matches(
                    root.file_name().and_then(|s| s.to_str()).unwrap_or(""),
                    request,
                    false,
                )?
            {
                let (files, markers) = Fs::facts(&root)?;
                candidates.add(
                    root,
                    files,
                    markers,
                    120,
                    "registry alias or project name matched request",
                    "registry",
                    &aliases,
                )?;
            }
        }
        Some(())
    }

    pub(crate) fn path(raw: &str) -> Option<PathBuf> {
        let expanded = expand_vars(raw)?;
        if expanded == "~" || expanded.starts_with("~/") {
            return Some(python_path(
                &PathBuf::from(env::var_os("HOME")?)
                    .join(expanded.strip_prefix("~/").unwrap_or("")),
            ));
        }
        if expanded.starts_with('~') {
            return None;
        } // Named-user lookup stays Python-owned.
        Some(python_path(Path::new(&expanded)))
    }
}

fn python_path(path: &Path) -> PathBuf {
    let normalized: PathBuf = path.components().collect();
    if normalized.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        normalized
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(v) => v.as_f64() != Some(0.0),
        Value::String(v) => !v.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}

fn expand_vars(mut raw: &str) -> Option<String> {
    let mut expanded = String::new();
    while let Some(index) = raw.find('$') {
        expanded.push_str(&raw[..index]);
        let tail = &raw[index + 1..];
        let (name, size) = if let Some(braced) = tail.strip_prefix('{') {
            match braced.find('}') {
                Some(end) => (&braced[..end], end + 2),
                None => ("", 0),
            }
        } else {
            let end = tail
                .bytes()
                .take_while(|c| c.is_ascii_alphanumeric() || *c == b'_')
                .count();
            (&tail[..end], end)
        };
        if size == 0 {
            expanded.push('$');
            raw = tail;
            continue;
        }
        match env::var(name) {
            Ok(value) => expanded.push_str(&value),
            Err(env::VarError::NotPresent) => expanded.push_str(&raw[index..index + size + 1]),
            Err(_) => return None,
        }
        raw = &tail[size..]; // No recursive expansion of substituted values.
    }
    expanded.push_str(raw);
    Some(expanded)
}
