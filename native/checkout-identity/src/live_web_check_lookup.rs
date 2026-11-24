//! owner: bounded local live-web check lookup.
//! allowed imports: read-only filesystem probes and shared Python text, JSON and date parsing.
//! forbidden imports: claims state, log writes, authority decisions and network.
//! callers/tests: path-claims check and differential log fixtures.
//! verification: truncated tails, file suffixes, inclusive timestamps and malformed rows.
use crate::{
    discovery_fs::DiscoveryFs,
    overhead_stamp::OverheadStamp,
    python_json::{InputDiagnostic, PythonJson, Value as PythonValue},
    python_text::PythonText,
    text::Text,
};
use serde_json::{json, Value};
#[path = "live_web_check_report.rs"]
mod report;
use std::{
    borrow::Cow,
    fs::OpenOptions,
    io::{self, Read, Seek, SeekFrom},
    os::unix::fs::OpenOptionsExt,
    path::Path,
};

pub(super) struct LiveWebCheckLookup;

impl LiveWebCheckLookup {
    const LIMIT: u64 = 64 * 1024;
    // OverheadStamp counts microseconds from ordinal zero. datetime.timestamp
    // compares seconds since 1970, treating naive stamps in this caller as UTC.
    const EPOCH: i64 = 719163 * 86_400_000_000;

    pub(super) fn history(input: &Value) -> Option<Value> {
        let project = Self::project(input)?;
        let limit = input.get("tail_bytes")?.as_u64()?;
        if limit > Self::LIMIT {
            return None;
        }
        let data = Self::tail(project, limit)?;
        let text = String::from_utf8_lossy(&data);
        let lines = Self::entries(&text)?
            .into_iter()
            .map(|(line, _)| line)
            .collect::<Vec<_>>();
        // Return original lines as one array to preserve Python's numeric values.
        Some(json!({"checks_json": format!("[{}]", lines.join(","))}))
    }

    pub(super) fn probe(input: &Value) -> Option<Value> {
        let project = Self::project(input)?;
        let files = input
            .get("files")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let options = input.get("report");
        let wanted = if options.is_some() {
            files
                .into_iter()
                .map(|raw| Self::file_filter(project, raw))
                .collect::<Option<Vec<_>>>()?
        } else {
            files.into_iter().map(str::to_owned).collect()
        };
        let floor = match input.get("since") {
            Some(Value::Null) => None,
            Some(value) => Self::epoch(value.as_str()?)?,
            // Keep accepting an epoch from earlier library clients.
            None if options.is_none() => match input.get("floor")? {
                Value::Null => None,
                value => Some(value.as_f64()?),
            },
            None => return None,
        };
        let data = Self::tail(project, Self::LIMIT)?;
        let text = String::from_utf8_lossy(&data);
        for (line, entry) in Self::entries(&text)?.into_iter().rev() {
            if let Some(floor) = floor {
                let time = entry
                    .get("time")
                    .map(Self::python_string)
                    .unwrap_or_default();
                let Some(epoch) = Self::epoch(&time)? else {
                    continue;
                };
                if epoch < floor {
                    continue;
                }
            }
            if !wanted.is_empty() {
                let Some(files) = entry.get("files").and_then(|value| value.as_array()) else {
                    continue;
                };
                if !files.iter().any(|file| {
                    let file = Self::python_string(file);
                    wanted.iter().any(|want| Self::same_file(&file, want))
                }) {
                    continue;
                }
            }
            if let Some(options) = options {
                return report::LiveWebCheckReport::render(Some(&entry), options);
            }
            // Return one original JSON line, so Python can retain numeric and
            // serialization behavior without reparsing the unselected rows.
            return Some(json!({"line": line}));
        }
        if let Some(options) = options {
            return report::LiveWebCheckReport::render(None, options);
        }
        Some(json!({"line": null}))
    }

    fn project(input: &Value) -> Option<&Path> {
        let project = Path::new(input.get("project")?.as_str()?);
        (project.is_absolute() && project.canonicalize().ok()? == project).then_some(project)
    }

    fn entries(text: &str) -> Option<Vec<(&str, PythonValue)>> {
        let mut entries = Vec::new();
        for line in PythonText::splitlines(text) {
            match PythonJson::parse_with_diagnostic(line, Some(640), None) {
                Ok(Some(entry)) if entry.is_object() => entries.push((line, entry)),
                Ok(Some(_)) | Err(InputDiagnostic::Syntax(_)) => {}
                _ => return None,
            }
        }
        Some(entries)
    }

    fn python_string(value: &PythonValue) -> Cow<'_, str> {
        value
            .as_str()
            .map_or_else(|| Cow::Owned(PythonJson::string(value)), Cow::Borrowed)
    }

    fn file_filter(project: &Path, raw: &str) -> Option<String> {
        // Named homes and uncertain filesystem resolution use pathlib.
        let path = if raw.starts_with('~') {
            DiscoveryFs::expand(Path::new(&Text::norm_path(raw)))?
        } else {
            Path::new(raw).to_owned()
        };
        if !path.is_absolute() {
            return Some(Text::lexical_clean(raw));
        }
        let resolved = DiscoveryFs::resolve(&path)?;
        let Ok(relative) = resolved.strip_prefix(project) else {
            return Some(raw.to_owned());
        };
        let relative = relative.to_str()?;
        Some(if relative.is_empty() { "." } else { relative }.to_owned())
    }

    fn epoch(raw: &str) -> Option<Option<f64>> {
        let Some(stamp) = OverheadStamp::parse(raw)? else {
            return Some(None);
        };
        let ticks = stamp.ticks() - Self::EPOCH;
        // A larger integer could round once on conversion and again on division.
        (ticks.unsigned_abs() <= 1 << 53).then_some(Some(ticks as f64 / 1_000_000.0))
    }

    fn same_file(first: &str, second: &str) -> bool {
        let (first, second) = (first.trim_matches('/'), second.trim_matches('/'));
        !first.is_empty()
            && !second.is_empty()
            && (first == second
                || first
                    .strip_suffix(second)
                    .is_some_and(|prefix| prefix.ends_with('/'))
                || second
                    .strip_suffix(first)
                    .is_some_and(|prefix| prefix.ends_with('/')))
    }

    fn tail(project: &Path, limit: u64) -> Option<Vec<u8>> {
        let path = project.join(".moru/live-web/checks.jsonl");
        match path.canonicalize() {
            Ok(resolved) if resolved == path => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Some(Vec::new()),
            _ => return None,
        }
        let mut file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .ok()?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let size = file.seek(SeekFrom::End(0)).ok()?;
        let start = size.saturating_sub(limit);
        file.seek(SeekFrom::Start(start)).ok()?;
        let mut data = Vec::new();
        file.take(limit + 1).read_to_end(&mut data).ok()?;
        if data.len() as u64 != size - start {
            return None;
        }
        if start > 0 {
            let first = data.iter().position(|&byte| byte == b'\n');
            return Some(first.map_or_else(Vec::new, |first| data.split_off(first + 1)));
        }
        Some(data)
    }
}
