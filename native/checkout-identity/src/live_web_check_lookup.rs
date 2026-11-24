//! owner: bounded local live-web check lookup.
//! allowed imports: read-only filesystem probes and shared Python text, JSON and date parsing.
//! forbidden imports: claims state, log writes, authority decisions and network.
//! callers/tests: path-claims check and differential log fixtures.
//! verification: truncated tails, file suffixes, inclusive timestamps and malformed rows.
use crate::{
    discovery_fs::DiscoveryFs,
    overhead_stamp::OverheadStamp,
    python_json::{InputDiagnostic, PythonJson},
    python_text::PythonText,
    text::Text,
};
use serde_json::{json, Value};
#[path = "live_web_check_report.rs"]
mod report;
use std::{
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

    pub(super) fn probe(input: &Value) -> Option<Value> {
        let project = Path::new(input.get("project")?.as_str()?);
        if !project.is_absolute() || project.canonicalize().ok()? != project {
            return None;
        }
        let files = input
            .get("files")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let options = input.get("report");
        let (wanted, floor) = if options.is_some() {
            let wanted = files
                .into_iter()
                .map(|raw| Self::file_filter(project, raw))
                .collect::<Option<Vec<_>>>()?;
            let floor = match input.get("since")? {
                Value::Null => None,
                value => Self::epoch(value.as_str()?)?,
            };
            (wanted, floor)
        } else {
            let floor = match input.get("floor")? {
                Value::Null => None,
                value => Some(value.as_f64()?),
            };
            (files.into_iter().map(str::to_owned).collect(), floor)
        };
        let data = Self::tail(project)?;
        let text = String::from_utf8_lossy(&data);
        let mut entries = Vec::new();
        for line in PythonText::splitlines(&text) {
            match PythonJson::parse_with_diagnostic(line, Some(640), None) {
                Ok(Some(entry)) if entry.is_object() => entries.push((line, entry)),
                Ok(Some(_)) | Err(InputDiagnostic::Syntax(_)) => {}
                _ => return None,
            }
        }
        for (line, entry) in entries.into_iter().rev() {
            if let Some(floor) = floor {
                let time = match entry.get("time") {
                    Some(value) => value.as_str()?,
                    None => "",
                };
                let Some(epoch) = Self::epoch(time)? else {
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
                let files = files
                    .iter()
                    .map(|value| value.as_str())
                    .collect::<Option<Vec<_>>>()?;
                if !files
                    .iter()
                    .any(|file| wanted.iter().any(|want| Self::same_file(file, want)))
                {
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

    fn tail(project: &Path) -> Option<Vec<u8>> {
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
        let start = size.saturating_sub(Self::LIMIT);
        file.seek(SeekFrom::Start(start)).ok()?;
        let mut data = Vec::new();
        file.take(Self::LIMIT + 1).read_to_end(&mut data).ok()?;
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
