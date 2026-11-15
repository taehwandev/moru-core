//! owner: existing RegistryRead prepared retention preview;
//! allowed imports: shared identity rows, LocalState, PythonJson, std and JSON;
//! forbidden imports: writes, deletion, locks, registry reads or authority mutation;
//! callers/tests: private retention-plan adapter and focused sibling temp-FS tests;
//! verification: offline Rust debug tests and parent Python reference parity.
use super::RegistryRead;
use crate::{
    callback_state::LocalState,
    python_json::{ParseOutcome, PythonJson},
};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs,
    io::Read,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

struct Prepared<'a> {
    directory: &'a Path,
    states: Option<&'a serde_json::Map<String, Value>>,
    uncertain: bool,
    protected: HashSet<&'a str>,
    cutoff: f64,
    orphan_cutoff: f64,
    keep: usize,
    holding: HashSet<&'a str>,
    settled: HashSet<&'a str>,
    finished: HashSet<&'a str>,
}

impl<'a> Prepared<'a> {
    fn read(payload: &'a Value) -> Option<Self> {
        if payload.as_object()?.len() != 11
            || payload.get("int_digits")?.as_u64()?
                != option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
                    .unwrap_or("0")
                    .parse::<u64>()
                    .ok()?
        {
            return None;
        }
        let directory = Path::new(payload.get("directory")?.as_str()?);
        if !directory.is_absolute()
            || directory.canonicalize().ok()?.as_path() != directory
            || !directory.is_dir()
        {
            return None;
        }
        LocalState::safe_path(Path::new("/"), directory)?;
        let states = match payload.get("registry_states")? {
            Value::Null => None,
            Value::Object(states) if states.values().all(Value::is_string) => Some(states),
            _ => return None,
        };
        let cutoff = payload.get("cutoff")?.as_f64()?;
        let orphan_cutoff = payload.get("orphan_cutoff")?.as_f64()?;
        if !cutoff.is_finite() || !orphan_cutoff.is_finite() {
            return None;
        }
        Some(Self {
            directory,
            states,
            cutoff,
            orphan_cutoff,
            uncertain: payload.get("registry_uncertain")?.as_bool()?,
            protected: string_set(payload.get("protected")?)?,
            keep: usize::try_from(payload.get("keep")?.as_u64()?).ok()?,
            holding: string_set(payload.get("holding_states")?)?,
            settled: string_set(payload.get("settled_states")?)?,
            finished: string_set(payload.get("finished_phases")?)?,
        })
    }
}

#[derive(Default)]
struct Classified {
    finished: Vec<String>,
    unfinished: Vec<String>,
    abandoned: Vec<String>,
    orphaned: Vec<String>,
    old_orphans: Vec<String>,
    unclassified: Vec<String>,
}

impl RegistryRead {
    pub(super) fn retention_phase(path: &Path, remaining: &mut usize) -> Option<String> {
        phase(path, remaining)
    }

    pub(super) fn retention_plan(payload: &Value) -> Option<Value> {
        let prepared = Prepared::read(payload)?;
        let mut entries = Vec::new();
        for entry in fs::read_dir(prepared.directory).ok()? {
            let path = entry.ok()?.path();
            let name = path.file_name()?.to_str()?.to_owned();
            entries.push((name, path));
            if entries.len() > 4096 {
                return None;
            }
        }
        entries.sort_by(|a, b| a.0.cmp(&b.0));
        let mut remaining = 8 * 1024 * 1024;
        let classified = classify(&prepared, entries, |path| phase(path, &mut remaining))?;
        Self::project_plan(&prepared, classified)
    }

    fn project_plan(prepared: &Prepared<'_>, classified: Classified) -> Option<Value> {
        // Read every finished mtime afresh, then preserve entry order for ties.
        let mut finished = classified
            .finished
            .into_iter()
            .map(|name| Some((name.clone(), modified(&prepared.directory.join(name))?)))
            .collect::<Option<Vec<_>>>()?;
        finished.sort_by(|a, b| b.1.total_cmp(&a.1));
        let finished: Vec<_> = finished.into_iter().map(|(name, _)| name).collect();
        let keep = prepared.keep.min(finished.len());
        let removable: Vec<_> = finished[keep..]
            .iter()
            .chain(&classified.abandoned)
            .chain(&classified.old_orphans)
            .cloned()
            .collect();
        if removable.len() > 256 {
            return None;
        }
        let mut remaining = 4096;
        let identities = removable
            .iter()
            .map(|name| {
                Some(json!([
                    name,
                    Self::identity_rows(&prepared.directory.join(name), &mut remaining)?
                ]))
            })
            .collect::<Option<Vec<_>>>()?;
        Some(json!({
            "finished": finished, "unfinished": classified.unfinished,
            "abandoned": classified.abandoned, "orphaned": classified.orphaned,
            "unclassified": classified.unclassified, "kept": finished[..keep],
            "removable": removable, "identities": identities,
        }))
    }
}

fn string_set(value: &Value) -> Option<HashSet<&str>> {
    value.as_array()?.iter().map(Value::as_str).collect()
}

fn classify(
    prepared: &Prepared<'_>,
    entries: Vec<(String, PathBuf)>,
    mut read_phase: impl FnMut(&Path) -> Option<String>,
) -> Option<Classified> {
    let mut result = Classified::default();
    for (name, path) in entries {
        if !run_directory(&path)?
            || name.len() != 32
            || !name
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            result.unclassified.push(name);
            continue;
        }
        let state = prepared
            .states
            .and_then(|states| states.get(&name))
            .and_then(Value::as_str);
        if prepared.uncertain
            || prepared.protected.contains(name.as_str())
            || state.is_some_and(|state| prepared.holding.contains(state))
        {
            result.unfinished.push(name);
        } else if prepared.states.is_some() && state.is_none() {
            if touched_at(&path) < prepared.orphan_cutoff {
                result.old_orphans.push(name.clone());
            }
            result.orphaned.push(name);
        } else if prepared.finished.contains(read_phase(&path)?.as_str())
            || state.is_some_and(|state| prepared.settled.contains(state))
        {
            result.finished.push(name);
        } else if !read_phase(&path)?.is_empty() && touched_at(&path) < prepared.cutoff {
            result.abandoned.push(name);
        } else {
            result.unfinished.push(name);
        }
    }
    Some(result)
}

fn run_directory(path: &Path) -> Option<bool> {
    let metadata = match fs::metadata(path) {
        Ok(value) => value,
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::EBADF | libc::ELOOP)
            ) =>
        {
            return Some(false)
        }
        Err(_) => return None,
    };
    if !metadata.is_dir() {
        return Some(false);
    }
    Some(!fs::symlink_metadata(path).ok()?.file_type().is_symlink())
}

fn modified(path: &Path) -> Option<f64> {
    let metadata = fs::metadata(path).ok()?;
    Some(metadata.mtime() as f64 + metadata.mtime_nsec() as f64 * 1e-9)
}

fn touched_at(path: &Path) -> f64 {
    modified(path).unwrap_or_else(|| match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => duration.as_secs_f64(),
        Err(error) => -error.duration().as_secs_f64(),
    })
}

fn phase(path: &Path, remaining: &mut usize) -> Option<String> {
    let packet = path.join("continuation.json");
    match fs::symlink_metadata(&packet) {
        Ok(metadata) if metadata.file_type().is_symlink() => return None,
        Ok(metadata) if metadata.is_dir() => return Some(String::new()),
        Ok(metadata) if !metadata.is_file() => return None,
        Err(_) => return Some(String::new()),
        _ => {}
    }
    let file = match fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(packet)
    {
        Ok(file) => file,
        Err(error) if error.raw_os_error() == Some(libc::ELOOP) => return None,
        Err(_) => return Some(String::new()),
    };
    if !file.metadata().ok()?.is_file() {
        return None;
    }
    let mut bytes = Vec::new();
    let limit = (*remaining).min(1024 * 1024);
    let read = file.take(limit as u64 + 1).read_to_end(&mut bytes);
    if bytes.len() > limit {
        return None;
    }
    *remaining -= bytes.len();
    if read.is_err() {
        return Some(String::new());
    }
    let Ok(text) = std::str::from_utf8(&bytes) else {
        return Some(String::new());
    };
    match PythonJson::parse_outcome(text) {
        ParseOutcome::Invalid => Some(String::new()),
        ParseOutcome::Unsupported => None,
        ParseOutcome::Value(payload) => Some(
            payload
                .get("phase")
                .filter(|value| PythonJson::truthy(value))
                .map(PythonJson::string)
                .unwrap_or_default(),
        ),
    }
}

#[cfg(test)]
#[path = "registry_retention_plan_tests.rs"]
mod tests;
