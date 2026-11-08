//! owner: CardResume; allowed imports: std metadata, guarded reader, shared JSON;
//! forbidden imports: writes, SQL, processes, latest-session discovery or caching;
//! callers/tests: native resume ingress; verification: binding/menu/path fixtures.
use crate::{
    overhead_process::OverheadProcess,
    python_json::{ParseOutcome, PythonJson, Value},
};
use serde_json::Value as Json;
use std::{
    fs,
    path::{Component, Path, PathBuf},
};

pub(crate) struct CardResume;

impl CardResume {
    pub(crate) fn menu(snapshot: &Json) -> Option<Vec<(String, String)>> {
        let mut options = Vec::new();
        // Resolve every binding before touching menu-only fields or exposing UI.
        for card in snapshot.as_array()? {
            if let Some(session) = Self::binding(card)? {
                options.push((card, session));
            }
        }
        let mut rows = Vec::new();
        for (index, (card, session)) in options.into_iter().enumerate() {
            let summary = Self::field(card, "summary")?.text()?;
            let state = Self::field(card, "state")?.text()?;
            let date: String = Self::field(card, "updated_at")?
                .text()?
                .chars()
                .take(10)
                .collect();
            rows.push((
                format!("{}. {summary} [{state}, {date}]", index + 1),
                session,
            ));
        }
        Some(rows)
    }

    fn binding(card: &Json) -> Option<Option<String>> {
        let runtime = Self::field(card, "runtime")?;
        let session = Self::field(card, "session_id")?;
        if !runtime.truthy() && !session.truthy() {
            return Self::legacy(card);
        }
        Some(match (runtime, session) {
            (Cell::Text("codex"), Cell::Text(session)) if Self::uuid(session) => {
                Some(session.into())
            }
            _ => None,
        })
    }

    fn legacy(card: &Json) -> Option<Option<String>> {
        let run = Self::field(card, "run_id")?;
        let run = if run.truthy() {
            run.text()?
        } else {
            Self::field(card, "work_id")?.text()?
        };
        if run.len() != 32
            || !run
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Some(None);
        }
        let project = Self::field(card, "project")?.text()?;
        if project.contains('\0') || project.starts_with("//") {
            return None;
        }
        let path = Path::new(if project.is_empty() { "." } else { project })
            .join(".moru/runs")
            .join(run)
            .join("preflight.json");
        let Some(payload) = Self::evidence(&path)? else {
            return Some(None);
        };
        if !payload.is_object() {
            return Some(None);
        }
        let work = match payload.get("work") {
            None => &Value::Null,
            Some(Value::Object(work)) => work.get("id").unwrap_or(&Value::Null),
            Some(_) => return Some(None),
        };
        if work.as_str() != Some(Self::field(card, "work_id")?.text()?) {
            return Some(None);
        }
        let Some(binding) = payload
            .get("runtime_session")
            .filter(|binding| PythonJson::truthy(binding))
        else {
            return Some(None);
        };
        Some(
            match (
                binding.get("runtime").and_then(Value::as_str),
                binding.get("session_id").and_then(Value::as_str),
            ) {
                (Some("codex"), Some(session)) if Self::uuid(session) => Some(session.into()),
                _ => None,
            },
        )
    }

    fn uuid(value: &str) -> bool {
        value.len() == 36
            && value.bytes().enumerate().all(|(index, byte)| {
                if matches!(index, 8 | 13 | 18 | 23) {
                    byte == b'-'
                } else {
                    byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
                }
            })
    }

    fn field<'a>(card: &'a Json, name: &str) -> Option<Cell<'a>> {
        for pair in card.as_array()? {
            let pair = pair.as_array()?;
            if pair.len() != 2 {
                return None;
            }
            if pair[0].as_str()? != name {
                continue;
            }
            return match pair[1].as_array()?.as_slice() {
                [tag] if tag == "null" => Some(Cell::Null),
                [tag, value] if tag == "text" => Some(Cell::Text(value.as_str()?)),
                [tag, value] if tag == "integer" => Some(Cell::Integer(value.as_i64()?)),
                [tag, value] if tag == "real" => Some(Cell::Real(value.as_str()?.parse().ok()?)),
                [tag, value] if tag == "blob" => {
                    let hex = value.as_str()?;
                    if hex.len() % 2 != 0
                        || !hex
                            .bytes()
                            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                    {
                        return None;
                    }
                    Some(Cell::Blob(hex))
                }
                _ => None,
            };
        }
        Some(Cell::Null)
    }

    fn evidence(path: &Path) -> Option<Option<Value>> {
        let absolute = if path.is_absolute() {
            path.to_owned()
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
                    return Some(None)
                }
                Err(_) => return None,
            }
        }
        let bytes = OverheadProcess::read(absolute.to_str()?)?;
        let Ok(text) = std::str::from_utf8(&bytes) else {
            return Some(None);
        };
        match PythonJson::parse_outcome(text) {
            ParseOutcome::Value(value) => Some(Some(value)),
            ParseOutcome::Invalid => Some(None),
            ParseOutcome::Unsupported => None,
        }
    }
}

enum Cell<'a> {
    Null,
    Text(&'a str),
    Integer(i64),
    Real(f64),
    Blob(&'a str),
}
impl<'a> Cell<'a> {
    fn text(&self) -> Option<&'a str> {
        if let Self::Text(value) = self {
            Some(value)
        } else {
            None
        }
    }
    fn truthy(&self) -> bool {
        match self {
            Self::Null => false,
            Self::Text(value) | Self::Blob(value) => !value.is_empty(),
            Self::Integer(value) => *value != 0,
            Self::Real(value) => *value != 0.0,
        }
    }
}

#[cfg(test)]
#[path = "cards_resume_tests.rs"]
mod tests;
