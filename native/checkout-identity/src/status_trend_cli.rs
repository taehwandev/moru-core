//! Owner: efficiency trend CLI selection and rendering. Allowed imports: native trend pipeline,
//! discovery, source guard, Python JSON/text and status clock. Forbidden: writes and subprocesses.
//! Callers/tests: status process dispatch and native status command tests.
use crate::{
    completion_process::{status_trend_pipeline, status_trend_projects},
    discovery_fs::DiscoveryFs,
    pretool_guard::CallbackGuard,
    python_json::PythonJson,
    python_text::PythonText,
    status_snapshot::StatusSnapshot,
};
use serde_json::{json, Value};
use std::{
    env,
    ffi::OsStr,
    path::{Path, PathBuf},
};

#[derive(Default)]
struct Options<'a> {
    all: bool,
    project: Option<&'a str>,
    workspace: Option<&'a str>,
    spill: Option<&'a str>,
    codex: Option<&'a str>,
    month: &'a str,
}

impl<'a> Options<'a> {
    fn parse(words: &[&'a str]) -> Option<Self> {
        let mut options = Self::default();
        let mut iter = words.iter().copied();
        while let Some(arg) = iter.next() {
            let (key, attached) = match arg.split_once('=') {
                Some((key, value)) => (key, Some(value)),
                None => (arg, None),
            };
            match (key, attached) {
                ("--efficiency-trends" | "--validate", None) => continue,
                ("--all-projects", None) => {
                    options.all = true;
                    continue;
                }
                _ => {}
            }
            let value = match attached {
                Some(value) => value,
                None => iter.next().filter(|s| !s.starts_with('-'))?,
            };
            match key {
                "--project" => options.project = Some(value),
                "--workspace-root" => options.workspace = Some(value),
                "--spill-db" => options.spill = Some(value),
                "--codex-db" => options.codex = Some(value),
                "--month" => options.month = value,
                _ => return None,
            }
        }
        Some(options)
    }
}

fn expand(value: &str) -> Option<PathBuf> {
    if value.starts_with("//") {
        return None;
    }
    DiscoveryFs::expand(Path::new(if value.is_empty() { "." } else { value }))
}

pub(crate) fn snapshot(launcher: &OsStr, words: &[&str]) -> Option<String> {
    let options = Options::parse(words)?;
    CallbackGuard::root(launcher, "agent-os-status")?;
    let home = PathBuf::from(env::var_os("HOME")?);
    let projects = if options.all {
        let workspace = match options.workspace {
            Some(value) => expand(value)?,
            None => home.join("git"),
        };
        let root = DiscoveryFs::resolve_allow_missing(&workspace)?;
        let result = status_trend_projects::discover(&json!({"root": root.to_str()?}))?;
        result
            .get("projects")?
            .as_array()?
            .iter()
            .map(|p| Some(PathBuf::from(p.as_str()?)))
            .collect::<Option<Vec<_>>>()?
    } else {
        let project = match options.project {
            Some(value) => expand(value)?,
            None => env::current_dir().ok()?,
        };
        vec![DiscoveryFs::resolve_allow_missing(&project)?]
    };
    let spill = match options.spill {
        Some(value) => expand(value)?,
        None => home.join("Library/Application Support/Spill/token-metering/events.sqlite3"),
    };
    let codex = match options.codex {
        Some(value) => expand(value)?,
        None => home.join(".codex/state_5.sqlite"),
    };
    let month = options.month.trim_matches(PythonText::whitespace);
    let mut report = status_trend_pipeline::report(&projects, &spill, &codex, month)?;
    report.as_object_mut()?.insert(
        "captured_at".into(),
        Value::String(StatusSnapshot::capture_time()?),
    );
    report.sort_all_objects();
    let value = PythonJson::parse(&serde_json::to_string(&report).ok()?)?;
    Some(PythonJson::render(&value, false, false)? + "\n")
}
