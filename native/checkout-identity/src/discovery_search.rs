//! Owner: read-only discovery selection for registry-free requests.
//! Allowed: std, serde_json, discovery_fs, existing whitespace renderer.
//! Forbidden: writes, launch/effect policy.
//! Callers/tests: discovery_process; native discovery and existing discovery tests.
use crate::discovery_fs::DiscoveryFs as Fs;
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    env, fs,
    path::{Path, PathBuf},
};

pub(crate) struct DiscoverySearch;

impl DiscoverySearch {
    pub(crate) fn find(
        request: &str,
        cwd: &Path,
        registry: Option<&Path>,
        roots: &[PathBuf],
        depth: usize,
        defaults: bool,
        snapshot: Option<&Value>,
    ) -> Option<Value> {
        // Explicit request paths need Python's shlex/cleanup grammar. Registry
        // aliases and workspace groups remain with their existing policy owner.
        if request.len() > 16384 || request.contains(['/', '\\', '~', '$', '.', '\'', '"', '`']) {
            return None;
        }
        let request = Fs::lower(request)?;
        let registered = match snapshot {
            Some(value) => value.clone(),
            None => load_registry(registry)?,
        };
        let mut scans = registry_roots(&registered)?;
        if let Some(paths) = env::var_os("MORU_PROJECT_SEARCH_ROOTS") {
            for path in env::split_paths(&paths).filter(|p| !p.as_os_str().is_empty()) {
                scans.push(Fs::expand(&path)?);
            }
        }
        scans.extend_from_slice(roots);
        if defaults {
            let home = PathBuf::from(env::var_os("HOME")?);
            scans.extend(
                [
                    "Documents",
                    "Developer",
                    "GitHub",
                    "git",
                    "Projects",
                    "Downloads",
                ]
                .map(|p| home.join(p)),
            );
        }
        let cwd = Fs::resolve(&Fs::expand(cwd)?)?;
        let candidates = collect(&request, &cwd, scans, depth)?;
        rank(&request, candidates)
    }
}

fn load_registry(registry: Option<&Path>) -> Option<Value> {
    let registry = match registry {
        Some(path) => path.to_owned(),
        None => match env::var("MORU_PROJECT_REGISTRY") {
            Ok(raw) if !raw.is_empty() => Fs::expand(Path::new(&raw))?,
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
    if Fs::exists(&registry)? {
        serde_json::from_str::<Value>(&fs::read_to_string(registry).ok()?).ok()
    } else {
        Some(json!({}))
    }
}

fn registry_roots(registered: &Value) -> Option<Vec<PathBuf>> {
    let mut scans = Vec::new();
    if let Some(map) = registered.as_object() {
        for key in ["projects", "workspace_groups"] {
            if map
                .get(key)
                .and_then(Value::as_array)
                .is_some_and(|v| !v.is_empty())
            {
                return None;
            }
        }
        if let Some(paths) = map.get("search_roots").and_then(Value::as_array) {
            for path in paths.iter().filter_map(Value::as_str) {
                scans.push(Fs::expand(Path::new(path))?);
            }
        }
    } else if registered.as_array().is_some_and(|v| !v.is_empty()) {
        return None;
    }
    Some(scans)
}

fn collect(
    request: &str,
    cwd: &Path,
    scans: Vec<PathBuf>,
    depth: usize,
) -> Option<BTreeMap<PathBuf, Value>> {
    let mut candidates = BTreeMap::new();
    if let Some(root) = Fs::root(&cwd)? {
        if !has_slug(&request) || name_matches(root.file_name()?.to_str()?, &request)? {
            let (files, markers) = Fs::facts(&root)?;
            add(
                &mut candidates,
                root,
                files,
                markers,
                65,
                "current working directory is inside a project",
                "cwd",
            )?;
        }
    }
    let mut seen = Vec::new();
    for root in scans {
        if seen.contains(&root) {
            continue;
        }
        seen.push(root.clone());
        if !Fs::exists(&root)? || !root.is_dir() {
            continue;
        }
        for (path, files, markers) in Fs::scan(&root, depth)? {
            let matched = name_matches(path.file_name()?.to_str()?, &request)?;
            add(
                &mut candidates,
                Fs::resolve(&path)?,
                files,
                markers,
                if matched { 100 } else { 35 },
                if matched {
                    "project name matched request under configured search root"
                } else {
                    "project marker found under configured search root"
                },
                "search_root",
            )?;
        }
    }
    Some(candidates)
}

fn rank(request: &str, candidates: BTreeMap<PathBuf, Value>) -> Option<Value> {
    let mut ranked: Vec<Value> = candidates.into_values().collect();
    for candidate in &mut ranked {
        let path = Path::new(candidate["path"].as_str()?);
        if name_matches(path.file_name()?.to_str()?, &request)? {
            candidate["confidence"] = json!(candidate["confidence"].as_i64()? + 12);
            unique(
                candidate.get_mut("reasons")?,
                "candidate name appeared in request",
            );
        }
    }
    ranked.sort_by(|a, b| {
        b["confidence"]
            .as_i64()
            .cmp(&a["confidence"].as_i64())
            .then_with(|| a["path"].as_str().cmp(&b["path"].as_str()))
    });
    let status = if ranked.is_empty() {
        "not_found"
    } else if ranked.len() == 1
        || ranked[0]["confidence"].as_i64()? - ranked[1]["confidence"].as_i64()? >= 20
    {
        "selected"
    } else {
        "ambiguous"
    };
    let selected = if status == "selected" {
        ranked[0].clone()
    } else {
        Value::Null
    };
    Some(json!({"status":status,"selected_project":selected,"candidates":ranked}))
}

fn unique(array: &mut Value, item: &str) {
    let value = json!(item);
    let list = array.as_array_mut().unwrap();
    if !list.contains(&value) {
        list.push(value);
    }
}

fn add(
    candidates: &mut BTreeMap<PathBuf, Value>,
    path: PathBuf,
    files: Vec<String>,
    markers: Vec<String>,
    base: i64,
    reason: &str,
    source: &str,
) -> Option<()> {
    let score = base
        + if files.is_empty() { 0 } else { 20 }
        + if markers.iter().any(|m| m == ".git") {
            10
        } else {
            0
        }
        + if markers.is_empty() { 0 } else { 5 };
    if let Some(existing) = candidates.get_mut(&path) {
        existing["confidence"] = json!(existing["confidence"].as_i64()?.max(score));
        unique(existing.get_mut("reasons")?, reason);
        unique(existing.get_mut("sources")?, source);
        for (key, items) in [("instruction_files", files), ("markers", markers)] {
            for item in items {
                unique(existing.get_mut(key)?, &item);
            }
        }
    } else {
        let text = path.to_str()?;
        candidates.insert(
            path.clone(),
            json!({"path":text,"confidence":score,"reasons":[reason],
            "instruction_files":files,"markers":markers,"sources":[source],"aliases":[]}),
        );
    }
    Some(())
}

fn boundary(c: u8) -> bool {
    c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_' || c == b'-'
}

fn has_slug(request: &str) -> bool {
    request.as_bytes().windows(3).any(|w| {
        w[0].is_ascii_alphanumeric() && matches!(w[1], b'-' | b'_') && w[2].is_ascii_alphanumeric()
    })
}

fn parts(value: &str) -> Vec<&str> {
    value
        .split(|c: char| !c.is_ascii_lowercase() && !c.is_ascii_digit())
        .filter(|v| !v.is_empty())
        .collect()
}

fn name_matches(name: &str, request: &str) -> Option<bool> {
    let name = Fs::lower(crate::statusline::Renderer::strip(name))?;
    let words = parts(&name);
    let normalized = words.join(" ");
    if name.is_empty()
        || [
            "app", "api", "backend", "client", "desktop", "frontend", "mobile", "server", "web",
        ]
        .contains(&normalized.as_str())
    {
        return Some(false);
    }
    for (start, _) in request.match_indices(&name) {
        let end = start + name.len();
        if (start == 0 || !boundary(request.as_bytes()[start - 1]))
            && (end == request.len() || !boundary(request.as_bytes()[end]))
        {
            return Some(true);
        }
    }
    Some(
        words.len() > 1
            && format!(" {} ", parts(request).join(" ")).contains(&format!(" {normalized} ")),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn names_keep_slug_and_generic_boundaries() {
        for (name, request, expected) in [
            ("moru-core", "moru core 수정", true),
            ("moru", "moru-core", false),
            ("web", "web", false),
            ("한글", "한글 수정", true),
            ("moru-core", "xmoru-core", false),
        ] {
            assert_eq!(name_matches(name, request), Some(expected));
        }
    }
}
