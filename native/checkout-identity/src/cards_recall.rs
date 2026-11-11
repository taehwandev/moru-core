//! owner: CardRecall; allowed imports: std metadata, guarded reader, shared JSON;
//! forbidden imports: SQL, writes, settlement, processes, providers;
//! callers/tests: readonly work-card recall; verification: selection/state/bounds fixtures.
use crate::{
    overhead_process::OverheadProcess,
    python_json::{ParseOutcome, PythonJson, Value},
};
use serde_json::{json, Value as Json};
use std::{
    collections::HashMap,
    fs,
    path::{Component, Path, PathBuf},
};

pub(crate) struct CardRecall;

impl CardRecall {
    pub(crate) fn evaluate(snapshot: &Json, current: &str) -> Option<Json> {
        let mut others = Vec::new();
        for card in snapshot.as_array()? {
            let id = Self::text(card, "work_id")??;
            if id != current {
                others.push((id, card));
            }
        }
        let mut cache = HashMap::new();
        let mut live = Vec::new();
        let mut stale = Vec::new();
        for (id, card) in others.iter().take(20) {
            if let Some(state) = Self::stale(card, id, &mut cache)? {
                stale.push(json!([id, state]));
            } else {
                live.push((*id, *card));
            }
        }
        let unchecked = others.len().saturating_sub(20);
        let mut lines = Vec::new();
        if !live.is_empty() || unchecked != 0 {
            lines.push("Open work cards in this repository (reference only; close finished ones with `work-cards close <work id>`):".to_owned());
            for (id, card) in live.iter().take(3) {
                let command = Self::text(card, "command")??;
                let date: String = Self::text(card, "updated_at")??.chars().take(10).collect();
                let summary = Self::text(card, "summary")??;
                lines.push(format!("- {id} [{command}, {date}] {summary}"));
            }
            let hidden = live.len().saturating_sub(3) + unchecked;
            if hidden != 0 {
                lines.push(format!("- {hidden} more: `work-cards list`"));
            }
        }
        Some(json!({"lines": lines, "stale": stale}))
    }

    // Inspect only the requested field: unsupported unused cells do not force replay.
    fn text<'a>(card: &'a Json, name: &str) -> Option<Option<&'a str>> {
        for pair in card.as_array()? {
            let pair = pair.as_array()?;
            if pair.len() != 2 {
                return None;
            }
            if pair[0].as_str()? != name {
                continue;
            }
            let cell = pair[1].as_array()?;
            return match cell.as_slice() {
                [tag] if tag == "null" => Some(None),
                [tag, value] if tag == "text" => Some(Some(value.as_str()?)),
                _ => None,
            };
        }
        Some(None)
    }

    fn stale(
        card: &Json,
        id: &str,
        cache: &mut HashMap<PathBuf, HashMap<String, String>>,
    ) -> Option<Option<&'static str>> {
        let raw = Self::text(card, "project")??;
        if raw.contains('\0') || raw.starts_with("//") {
            return None;
        }
        let project = Path::new(if raw.is_empty() { "." } else { raw });
        match fs::metadata(project) {
            Ok(metadata) if metadata.is_dir() => {}
            Ok(_) => return Some(Some("cancelled")),
            Err(error)
                if matches!(
                    error.raw_os_error(),
                    Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP | libc::EBADF)
                ) =>
            {
                return Some(Some("cancelled"))
            }
            Err(_) => return None,
        }
        let run = Self::text(card, "run_id")?
            .filter(|value| !value.is_empty())
            .unwrap_or(id);
        let states = Self::registry(project, cache)?;
        Some(match states.get(run).map(String::as_str).unwrap_or("") {
            "" | "cancelled" => Some("cancelled"),
            "completed" => Some("done"),
            _ => None,
        })
    }

    fn registry<'a>(
        project: &Path,
        cache: &'a mut HashMap<PathBuf, HashMap<String, String>>,
    ) -> Option<&'a HashMap<String, String>> {
        // pathlib drops lexical dots, including an initial "./" or a lone ".".
        // Keep parents, roots and aliases intact; the guarded read uses the original path.
        let key: PathBuf = project
            .components()
            .filter(|part| *part != Component::CurDir)
            .collect();
        if !cache.contains_key(&key) {
            cache.insert(key.clone(), Self::read_registry(project)?);
        }
        cache.get(&key)
    }

    fn read_registry(project: &Path) -> Option<HashMap<String, String>> {
        let path = project.join(".moru/run-registry.json");
        let absolute = if path.is_absolute() {
            path
        } else {
            std::env::current_dir().ok()?.join(path)
        };
        let mut prefix = PathBuf::new();
        for component in absolute.components() {
            if component == Component::ParentDir {
                return None;
            }
            prefix.push(component.as_os_str());
            if prefix == Path::new("/dev") || prefix == Path::new("/proc") {
                return None;
            }
            match fs::symlink_metadata(&prefix) {
                Ok(metadata) if metadata.is_symlink() => return None,
                Ok(_) => {}
                Err(error)
                    if matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) =>
                {
                    return Some(HashMap::new())
                }
                Err(_) => return None,
            }
        }
        let bytes = OverheadProcess::read(absolute.to_str()?)?;
        let Ok(text) = std::str::from_utf8(&bytes) else {
            return Some(HashMap::new());
        };
        let payload = match PythonJson::parse_outcome(text) {
            ParseOutcome::Value(value) => value,
            ParseOutcome::Invalid => return Some(HashMap::new()),
            ParseOutcome::Unsupported => return None,
        };
        let mut states = HashMap::new();
        if !payload.is_object() {
            return Some(states);
        }
        let runs = match payload.get("runs") {
            None | Some(Value::String(_) | Value::Object(_)) => return Some(states),
            Some(Value::Array(runs)) => runs,
            _ => return None,
        };
        for run in runs {
            let Some(id) = run.get("run_id").and_then(Value::as_str) else {
                continue;
            };
            let state = run
                .get("state")
                .filter(|value| PythonJson::truthy(value))
                .map(PythonJson::string)
                .unwrap_or_default();
            states.insert(id.to_owned(), state);
        }
        Some(states)
    }
}

#[cfg(test)]
#[path = "cards_recall_tests.rs"]
mod tests;
