//! Terminal-history/legacy-marker proof. Never interprets unfinished work.
use crate::callback_state::LocalState as State;
use serde_json::Value;
use std::{
    env, fs,
    path::{Path, PathBuf},
    time::SystemTime,
};

pub(crate) struct StopState;

impl StopState {
    // Advisory before the source scan; only rejects. Quiet admission rechecks
    // this exact condition under the existing project and registry locks.
    pub(crate) fn candidate(root: &Path) -> Option<()> {
        let registry = root.join(".moru/run-registry.json");
        State::safe_path(root, &registry)?;
        if !missing(&registry)? {
            let value: Value = serde_json::from_str(&State::read(&registry, 1048576)?).ok()?;
            if value.get("schema_version")?.as_u64()? != 1 {
                return None;
            }
            for run in value.get("runs")?.as_array()? {
                if !matches!(
                    run.get("state")?.as_str()?,
                    "completed" | "cancelled" | "failed"
                ) {
                    return None;
                }
            }
        }
        Some(())
    }

    pub(crate) fn quiet(project: &Path, state: &Path, runtime: &str, session: &str) -> Option<()> {
        let local = project.join(".moru");
        // Prove the nearest Git root is also Claude's opt-in root.
        State::safe_path(project, &local)?;
        if State::absent_dir(&local)?
            || local.canonicalize().ok()? == state.canonicalize().ok()?
            || local.canonicalize().ok()?
                == PathBuf::from(env::var_os("HOME")?)
                    .join(".moru")
                    .canonicalize()
                    .ok()?
        {
            return None;
        }
        for marker in ["moru-root", "projects.json", "bin/moru-hook"] {
            if !missing(&local.join(marker))? {
                return None;
            }
        }
        let mut roots = vec![project.to_owned()];
        if runtime == "claude" {
            let index = state.join("claude-session-projects").join(session);
            State::safe_path(state, &index)?;
            if !missing(&index)? {
                for line in State::read(&index, 8192)?.lines() {
                    let line = crate::statusline::Renderer::strip(line);
                    if line.is_empty() {
                        continue;
                    }
                    let path = Path::new(line);
                    if !path.is_absolute() || path.canonicalize().ok()?.as_path() != path {
                        return None;
                    }
                    if !roots.iter().any(|p| p == path) {
                        roots.push(path.to_owned());
                    }
                    if roots.len() > 8 {
                        return None;
                    }
                }
            }
        }
        for root in roots {
            let local = root.join(".moru");
            State::safe_path(&root, &local)?;
            // Python creates these locks on first lookup; never skip that effect.
            let _project_lock = State::lock(&local.join(".state.lock.lock"))?;
            let _registry_lock = State::lock(&local.join(".run-registry.json.lock"))?;
            Self::candidate(&root)?;
            if runtime == "claude" && !legacy_quiet(&root, session)? {
                return None;
            }
        }
        Some(())
    }
}

fn missing(path: &Path) -> Option<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Some(false),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Some(true),
        _ => None,
    }
}

fn timestamp(path: &Path) -> Option<Option<SystemTime>> {
    State::safe_path(path.parent()?, path)?;
    if missing(path)? {
        return Some(None);
    }
    let meta = fs::symlink_metadata(path).ok()?;
    if !meta.is_file() {
        return None;
    }
    Some(Some(meta.modified().ok()?))
}

fn legacy_quiet(root: &Path, session: &str) -> Option<bool> {
    let directory = root.join(".moru/claude-pretool-gate");
    State::safe_path(root, &directory)?;
    let Some(edited) = timestamp(&directory.join(format!("{session}.edited")))? else {
        return Some(true);
    };
    for suffix in ["finished", "settled", "stop-blocked"] {
        if timestamp(&directory.join(format!("{session}.{suffix}")))?
            .is_some_and(|stamp| stamp >= edited)
        {
            return Some(true);
        }
    }
    Some(false) // Shared finish.json remains Python-owned compatibility.
}
