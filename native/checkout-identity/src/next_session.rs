//! owner: NextSession; allowed imports: local state, PythonJson, candidates/process identity;
//! forbidden imports: writes/claims; callers/tests: next process/session tests;
//! verification: canonical session selection and registry chronology parity.
#[path = "next_candidates.rs"]
mod candidates;
#[path = "next_process_owner.rs"]
mod process_owner;
#[path = "next_state_root.rs"]
mod state_root;
#[path = "next_worker_scope.rs"]
mod worker_scope;
use crate::{
    callback_state::LocalState as State,
    python_json::{PythonJson, Value},
    python_text::PythonText,
    runtime_identity::RuntimeIdentity,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
};

pub(crate) struct NextSession;
impl NextSession {
    pub(super) fn discover(project: &Path) -> Option<Option<PathBuf>> {
        let Some((runtime, session)) = RuntimeIdentity::current()? else {
            return Some(None);
        };
        Self::discover_for(project, runtime, &session)
    }

    pub(crate) fn discover_for(
        project: &Path,
        runtime: &str,
        session: &str,
    ) -> Option<Option<PathBuf>> {
        Self::discover_binding(project, Some((runtime, session)))
    }

    pub(crate) fn discover_owned(project: &Path) -> Option<Option<PathBuf>> {
        if !matches!(
            worker_scope::WorkerScope::current(project)?,
            worker_scope::WorkerScope::Parent
        ) {
            return Some(None);
        }
        Self::discover_binding(project, None)
    }

    fn discover_binding(project: &Path, session: Option<(&str, &str)>) -> Option<Option<PathBuf>> {
        let Some(state) = state_root::NextStateRoot::resolve(project)? else {
            return Some(None);
        };
        // The legacy key uses Path.resolve even when no default evidence exists.
        State::safe_path(&state, &state.join("preflight.json"))?;
        let bindings = {
            let _project = State::lock(&state.join(".state.lock.lock"))?;
            let _registry = State::lock(&state.join(".run-registry.json.lock"))?;
            let path = state.join("run-registry.json");
            State::safe_path(&state, &path)?;
            if matches!(std::fs::symlink_metadata(&path), Err(e) if e.kind() == std::io::ErrorKind::NotFound)
            {
                return Some(None);
            }
            let raw = State::read(&path, 1024 * 1024)?;
            let payload = PythonJson::parse(&raw)?;
            Self::bindings(
                &payload,
                &candidates::Candidates::key(project, &state.join("preflight.json"))?,
            )?
        };
        if bindings.is_empty() {
            return Some(None);
        }
        match session {
            Some((runtime, session)) => Self::select(project, &state, &bindings, runtime, session),
            None => Self::select_owned(project, &state, bindings),
        }
    }

    fn select_owned(
        project: &Path,
        state: &Path,
        mut bindings: BTreeMap<String, Value>,
    ) -> Option<Option<PathBuf>> {
        let Some(owner) = process_owner::ProcessOwner::current()? else {
            return Some(None);
        };
        bindings.retain(|_, run| owner.matches(run.get("owner")));
        if bindings.is_empty() {
            return Some(None);
        }
        let (paths, _, complete) = candidates::Candidates::select(project, state, &bindings)?;
        if !complete {
            return None;
        }
        let mut matched = None;
        for path in paths {
            let key = candidates::Candidates::key(project, &path)?;
            let Some(run) = bindings.get(&key) else {
                continue;
            };
            let payload = PythonJson::parse(&State::read(&path, 1024 * 1024)?)?;
            let Some(bound) = payload.get("runtime_session").and_then(Value::as_object) else {
                continue;
            };
            let runtime = Self::text(bound.get("runtime"));
            let runtime = runtime.trim_matches(PythonText::whitespace);
            let session = Self::text(bound.get("session_id"));
            let session = session.trim_matches(PythonText::whitespace);
            // The reference excludes canonical strict names before applying
            // runtime alias normalization and generation equality.
            if runtime.is_empty() || matches!(runtime, "claude" | "codex") || session.is_empty() {
                continue;
            }
            if Self::matches(&payload, run, &Self::runtime_name(runtime), session)? {
                if matched.is_some() {
                    return Some(None);
                }
                matched = Some(path);
            }
        }
        Some(matched)
    }

    fn select(
        project: &Path,
        state: &Path,
        bindings: &BTreeMap<String, Value>,
        runtime: &str,
        session: &str,
    ) -> Option<Option<PathBuf>> {
        let (paths, outside, complete) = match worker_scope::WorkerScope::current(project)? {
            worker_scope::WorkerScope::Parent => {
                candidates::Candidates::select(project, state, bindings)?
            }
            worker_scope::WorkerScope::Invalid => return Some(None),
            worker_scope::WorkerScope::Selected(path) => (vec![path], Vec::new(), true),
        };
        let mut matched = Vec::new();
        let mut resolved = BTreeSet::new();
        for path in paths {
            let key = candidates::Candidates::key(project, &path)?;
            let Some(run) = bindings.get(&key) else {
                continue;
            };
            resolved.insert(key);
            let raw = match State::read(&path, 1024 * 1024) {
                Some(raw) => raw,
                None if matches!(std::fs::symlink_metadata(&path), Err(e) if e.kind() == std::io::ErrorKind::NotFound) => {
                    "{}".into()
                }
                None => return None,
            };
            let payload = PythonJson::parse(&raw)?;
            if Self::matches(&payload, run, runtime, session)? {
                matched.push(path);
            }
        }
        for path in outside {
            let key = candidates::Candidates::key(project, &path)?;
            if bindings.contains_key(&key) {
                resolved.insert(key);
            }
        }
        if !complete && resolved.len() != bindings.len() {
            return Some(None);
        }
        match matched.len() {
            0 => Some(None),
            1 => Some(matched.pop()),
            _ => {
                let Some(owner) = process_owner::ProcessOwner::current()? else {
                    return Some(None);
                };
                let mut owned = Vec::new();
                for path in matched {
                    let key = candidates::Candidates::key(project, &path)?;
                    if owner.matches(bindings[&key].get("owner")) {
                        owned.push(path);
                    }
                }
                if owned.len() == 1 {
                    Some(owned.pop())
                } else {
                    Some(None)
                }
            }
        }
    }

    fn bindings(payload: &Value, legacy: &str) -> Option<BTreeMap<String, Value>> {
        match payload.get("schema_version")? {
            Value::Number(n) if n.equals_u64(1) => {}
            Value::Bool(true) => {}
            _ => return None,
        }
        let mut latest = BTreeMap::new();
        for run in payload.get("runs")?.as_array()? {
            run.as_object()?;
            let mut key = Self::text(run.get("evidence_key"));
            if key.is_empty()
                && run.get("evidence_name").and_then(Value::as_str) == Some("preflight.json")
            {
                key = legacy.into();
            }
            if !key.is_empty() {
                latest.insert(key, run.clone());
            }
        }
        if latest
            .values()
            .any(|run| matches!(run.get("state"), Some(Value::Array(_) | Value::Object(_))))
        {
            return None;
        }
        latest.retain(|_, run| {
            matches!(
                run.get("state").and_then(Value::as_str),
                Some("running" | "paused" | "resuming")
            )
        });
        Some(latest)
    }

    pub(super) fn text(value: Option<&Value>) -> String {
        value
            .filter(|v| PythonJson::truthy(v))
            .map(PythonJson::string)
            .unwrap_or_default()
    }

    fn runtime_name(name: &str) -> String {
        let name = name.trim_matches(PythonText::whitespace).to_lowercase();
        if name == "agy" {
            "antigravity".into()
        } else {
            name
        }
    }

    fn matches(payload: &Value, run: &Value, runtime: &str, session: &str) -> Option<bool> {
        // Python evaluates this argument before entering same_runtime_session.
        let generation = Self::generation(run.get("resume_generation"))?;
        let Some(bound) = payload.get("runtime_session").and_then(Value::as_object) else {
            return Some(false);
        };
        if bound.get("session_id").and_then(Value::as_str) != Some(session) {
            return Some(false);
        }
        let name = Self::runtime_name(&Self::text(bound.get("runtime")));
        if name != runtime && name != "cli" {
            return Some(false);
        }
        let value = bound.get("resume_generation").unwrap_or(&Value::Null);
        Some(match value {
            Value::Null => !bound.contains_key("resume_generation") && generation == 0,
            Value::Bool(v) => generation == i64::from(*v),
            Value::Number(n) => {
                let text = n.text();
                if text.bytes().all(|c| c.is_ascii_digit() || c == b'-') {
                    text.parse::<i64>().ok() == Some(generation)
                } else {
                    n.as_float()? == generation as f64
                }
            }
            _ => false,
        })
    }

    fn generation(value: Option<&Value>) -> Option<i64> {
        let Some(value) = value.filter(|v| PythonJson::truthy(v)) else {
            return Some(0);
        };
        let number = match value {
            Value::Bool(v) => return Some(i64::from(*v)),
            Value::Number(n) => {
                let text = n.text();
                if text.bytes().all(|c| c.is_ascii_digit() || c == b'-') {
                    return text
                        .parse::<i64>()
                        .ok()
                        .filter(|n| n.unsigned_abs() <= (1u64 << 53));
                }
                n.as_float()?
            }
            Value::String(s) => {
                return s
                    .trim_matches(PythonText::whitespace)
                    .parse::<i64>()
                    .ok()
                    .filter(|n| n.unsigned_abs() <= (1u64 << 53))
            }
            _ => return None,
        };
        (number.is_finite() && number.abs() <= (1u64 << 53) as f64).then_some(number.trunc() as i64)
    }
}

#[cfg(test)]
#[path = "next_session_tests.rs"]
mod tests;
