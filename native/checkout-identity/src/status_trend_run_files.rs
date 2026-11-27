//! Owner: bounded run-evidence reads and field projection for status trends.
//! Allowed: read-only regular-file access, Python text helpers and JSON.
//! Forbidden: raw prompt/argv transport, state writes, locks, and providers.
//! Callers/tests: completion probe and the Python observability report fixture.
use crate::{
    discovery_fs::DiscoveryFs,
    python_input_file::{FileRead, PythonInputFile},
    text::Text,
};
use serde_json::{json, Map, Value};
use std::{collections::HashMap, fs, path::Path};

const MAX_ENTRIES: usize = 4096;
const MAX_FILE_BYTES: u64 = 1024 * 1024;
const MAX_SCAN_BYTES: u64 = 32 * MAX_FILE_BYTES;
const MAX_RESULT_BYTES: usize = 512 * 1024;
type Object = Map<String, Value>;

pub(super) fn read(request: &Value) -> Option<Value> {
    let state = Path::new(request.get("state_dir")?.as_str()?);
    if !state.is_absolute() || state.file_name()?.to_str()? != ".moru" {
        return None;
    }
    let mut remaining = MAX_SCAN_BYTES;
    let registry =
        read_object(&state.join("run-registry.json"), &mut remaining)?.unwrap_or_default();
    let mut by_id = HashMap::new();
    if let Some(rows) = registry.get("runs").and_then(Value::as_array) {
        for item in rows.iter().filter_map(Value::as_object) {
            if let Some(id) = item.get("run_id").filter(|id| truthy(id)) {
                by_id.insert(id.as_str()?, item);
            }
        }
    }

    let runs = state.join("runs");
    if !metadata(&runs)?.is_some_and(|meta| meta.is_dir()) {
        return Some(json!({"runs": []}));
    }
    let entries = fs::read_dir(&runs).ok()?;
    let mut names = Vec::new();
    for entry in entries.take(MAX_ENTRIES + 1) {
        if names.len() == MAX_ENTRIES {
            return None;
        }
        names.push(entry.ok()?.file_name().into_string().ok()?);
    }
    names.sort_unstable();
    let mut rows = Vec::new();
    let mut result_bytes = 0usize;
    for name in names {
        let directory = runs.join(&name);
        let Some(preflight) = read_object(&directory.join("preflight.json"), &mut remaining)?
        else {
            continue;
        };
        if preflight.is_empty() {
            continue;
        }
        let empty = Object::new();
        let registry = project(
            by_id.get(name.as_str()).copied().unwrap_or(&empty),
            &[
                "command",
                "started_at",
                "updated_at",
                "state",
                "resume_generation",
            ],
        )?;
        let (preflight, docs) = project_preflight(&preflight)?;
        let gates = read_object(&directory.join("gate-evidence.json"), &mut remaining)?;
        let reused = count_reused(gates.as_ref())?;
        let row = json!([name, registry, preflight, docs, reused]);
        result_bytes = result_bytes.checked_add(serde_json::to_vec(&row).ok()?.len() + 1)?;
        if result_bytes > MAX_RESULT_BYTES {
            return None;
        }
        rows.push(row);
    }
    Some(json!({"runs": rows}))
}

fn metadata(path: &Path) -> Option<Option<fs::Metadata>> {
    match fs::metadata(path) {
        Ok(meta) => Some(Some(meta)),
        Err(error) if matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) => {
            Some(None)
        }
        Err(_) => None,
    }
}

fn read_object(path: &Path, remaining: &mut u64) -> Option<Option<Object>> {
    let Some(meta) = metadata(path)? else {
        return Some(None);
    };
    if !meta.is_file() {
        return None;
    }
    let FileRead::Bytes(bytes) =
        PythonInputFile::read(path.as_os_str(), (*remaining).min(MAX_FILE_BYTES), false)?
    else {
        return None;
    };
    *remaining = remaining.checked_sub(bytes.len().try_into().ok()?)?;
    let source = std::str::from_utf8(&bytes).ok()?;
    // An unescaped CR inside a string is rejected in either parser.
    if source.contains('\r') {
        serde_json::from_str(&Text::universal_newlines(source))
            .ok()
            .map(Some)
    } else {
        serde_json::from_str(source).ok().map(Some)
    }
}

fn project(source: &Object, keys: &[&str]) -> Option<Object> {
    let mut fields = Object::new();
    for &key in keys {
        let Some(value) = source.get(key) else {
            continue;
        };
        // Keep Python-specific conversions of compound and floating inputs
        // on the reference path. Strings and exact integer scalars are safe.
        if !value.is_null()
            && !value.is_boolean()
            && !value.is_string()
            && value.as_i64().is_none()
            && value.as_u64().is_none()
        {
            return None;
        }
        if !matches!(key, "command" | "workflow_command")
            || value.as_str().and_then(route_token).is_some()
        {
            fields.insert(key.to_owned(), value.clone());
        }
    }
    Some(fields)
}

fn project_preflight(source: &Object) -> Option<(Object, usize)> {
    let mut result = project(source, &["timestamp"])?;
    for (section, keys) in [
        (
            "runtime_session",
            &[
                "runtime",
                "session_id",
                "resume_generation",
                "model",
                "reasoning_effort",
            ][..],
        ),
        ("work", &["previous_action", "id"][..]),
        ("route", &["command", "workflow_command"][..]),
    ] {
        if let Some(data) = source.get(section).and_then(Value::as_object) {
            result.insert(section.into(), Value::Object(project(data, keys)?));
        }
    }
    let docs = source
        .get("route")
        .and_then(|route| route.get("required_docs"))
        .and_then(Value::as_array)
        .map_or(0, Vec::len);
    if let Some(argv) = source
        .get("route_command")
        .and_then(|data| data.get("command"))
        .and_then(Value::as_array)
    {
        if argv.get(2).and_then(Value::as_str) == Some("route") {
            if let Some(token) = argv.get(3).and_then(Value::as_str).and_then(route_token) {
                result.insert(
                    "route_command".into(),
                    json!({"command": [null, null, "route", token]}),
                );
            }
        }
    }
    Some((result, docs))
}

fn route_token(raw: &str) -> Option<&str> {
    let token = Text::py_strip(raw);
    let mut bytes = token.bytes();
    ((2..=33).contains(&token.len())
        && bytes.next().is_some_and(|byte| byte.is_ascii_lowercase())
        && bytes.all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
        }))
    .then_some(token)
}

fn count_reused(file: Option<&Object>) -> Option<usize> {
    let Some(entries) = file
        .and_then(|file| file.get("entries"))
        .and_then(Value::as_array)
    else {
        return Some(0);
    };
    let mut total = 0;
    for entry in entries.iter().filter_map(Value::as_object) {
        let reused = entry.get("reused").is_some_and(truthy);
        let provenance = entry.get("reuse_provenance").is_some_and(Value::is_object);
        if reused || provenance {
            total += 1;
        } else if let Some(source) = entry.get("source").and_then(Value::as_str) {
            if matches!(
                DiscoveryFs::lower(Text::py_strip(source))?.as_str(),
                "reuse" | "reused"
            ) {
                total += 1;
            }
        }
    }
    Some(total)
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}
