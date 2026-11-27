//! Owner: compose the ordinary efficiency trend report from local project state.
//! Allowed imports: native trend readers, binding, summaries and Python text helpers.
//! Forbidden imports: process execution, database writes, clocks and providers.
//! Callers/tests: status CLI and its efficiency report fixtures.
use super::{
    status_trend_binding::TrendBinding, status_trend_metadata, status_trend_run_files,
    status_trend_sqlite::TrendSqlite, status_trends::StatusTrends,
};
use crate::{discovery_fs::DiscoveryFs, text::Text};
use serde_json::{json, Map, Value};
use std::{
    collections::{HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
};

fn database_rows(dataset: &str, path: &Path, ids: HashSet<&str>) -> Option<Vec<Value>> {
    if ids.is_empty() {
        return Some(Vec::new());
    }
    match fs::metadata(path) {
        Ok(meta) if meta.is_file() => {}
        Ok(_) => return Some(Vec::new()),
        Err(error)
            if matches!(
                error.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP)
            ) =>
        {
            return Some(Vec::new());
        }
        Err(_) => return None,
    }
    let mut result =
        TrendSqlite::read(&json!({"dataset": dataset, "path": path.to_str()?, "ids": ids}))?;
    Some(std::mem::take(result.get_mut("rows")?.as_array_mut()?))
}

fn codex_threads(rows: Vec<Value>) -> Option<Map<String, Value>> {
    let mut threads = Map::new();
    for row in rows {
        let [id, model, effort] = row.as_array()?.as_slice() else {
            return None;
        };
        let model = Text::py_strip(model.as_str()?);
        let effort = DiscoveryFs::lower(Text::py_strip(effort.as_str()?))?;
        threads.insert(
            id.as_str()?.to_owned(),
            json!([
                model,
                if effort.is_empty() {
                    "unknown"
                } else {
                    &effort
                }
            ]),
        );
    }
    Some(threads)
}

fn spill_events(rows: Vec<Value>) -> Option<HashMap<String, Vec<Value>>> {
    let mut events = HashMap::<String, Vec<Value>>::new();
    for row in rows {
        let [id, stamp, model, weighted, total, reasoning] = row.as_array()?.as_slice() else {
            return None;
        };
        if !stamp.as_str()?.is_empty() {
            events
                .entry(id.as_str()?.to_owned())
                .or_default()
                .push(json!([
                    stamp,
                    Text::py_strip(model.as_str()?),
                    weighted,
                    total,
                    reasoning
                ]));
        }
    }
    for session in events.values_mut() {
        // Stable sorting retains SQLite row order for simultaneous events.
        session.sort_by(|a, b| a[0].as_str().cmp(&b[0].as_str()));
    }
    Some(events)
}

pub(crate) fn report(
    projects: &[PathBuf],
    spill: &Path,
    codex: &Path,
    month: &str,
) -> Option<Value> {
    let month = Text::py_strip(month);
    let mut runs = Vec::new();
    for project in projects {
        if !project.is_absolute() {
            return None;
        }
        let state = project.join(".moru");
        let sources = status_trend_run_files::read(&json!({"state_dir": state.to_str()?}))?;
        let mut result = status_trend_metadata::project(&sources)?;
        let rows = result.get_mut("runs")?.as_array_mut()?;
        if runs.len().checked_add(rows.len())? > 32768 {
            return None;
        }
        runs.append(rows);
    }
    let ids = |key: &str| {
        runs.iter()
            .filter_map(|r| r[key].as_str())
            .filter(|id| !id.is_empty())
            .collect::<HashSet<_>>()
    };
    let threads = codex_threads(database_rows("codex", codex, ids("session_id"))?)?;
    let events = spill_events(database_rows("spill", spill, ids("spill_run_id"))?)?;
    for run in &mut runs {
        run["session_bound"] =
            json!(!run["runtime"].as_str()?.is_empty() && !run["session_id"].as_str()?.is_empty());
    }
    let mut bound = TrendBinding::bind(&json!({
        "runs": runs, "month": month, "codex_threads": threads, "spill_events": events
    }))?;
    let rows = bound.get_mut("runs")?.as_array_mut()?;
    for row in rows.iter_mut() {
        let fields = row.as_object_mut()?;
        for key in [
            "runtime_session",
            "session_id",
            "spill_run_id",
            "work_id",
            "run_id",
        ] {
            fields.remove(key);
        }
    }
    StatusTrends::report(&json!({"runs": rows, "month": month, "project_count": projects.len()}))
}
