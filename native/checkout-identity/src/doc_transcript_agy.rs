//! owner: read-only AGY transcript coverage projection;
//! allowed imports: guarded transcript reader, JSON, timestamp parsing and file metadata;
//! forbidden imports: marker/evidence writes, provider calls and delivery policy;
//! callers/tests: private doc-transcript probe and AGY required-doc process parity;
//! verification: full-file reads, compaction, path escaping and stale timestamps.
use super::DocTranscript;
use crate::{
    overhead_stamp::OverheadStamp,
    python_json::{ParseOutcome, PythonJson, Value},
};
use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{BufRead, BufReader, Read},
    os::unix::fs::MetadataExt,
    path::Path,
};

const MAX_TRANSCRIPT: u64 = 16 * 1024 * 1024;
const UNIX_EPOCH_TICKS: i64 = 719_163 * 86_400_000_000;

impl DocTranscript {
    pub(crate) fn agy_covered<'a>(
        path: &Path,
        rules: &Path,
        docs: &[&'a str],
    ) -> Option<Vec<&'a str>> {
        let (size, metadata) = Self::size(path);
        if size > MAX_TRANSCRIPT {
            return None;
        }
        let file = Self::open(path, &metadata?)?.ok()?;
        let mut wanted = HashMap::new();
        for &doc in docs {
            let file = rules.join(doc);
            wanted.insert(file.canonicalize().ok()?, (doc, file));
        }
        let mut covered = HashSet::new();
        let mut reader = BufReader::new(file.take(MAX_TRANSCRIPT + 1));
        let mut total = 0u64;
        let mut line = Vec::new();
        loop {
            line.clear();
            let bytes = reader.read_until(b'\n', &mut line).ok()?;
            if bytes == 0 {
                break;
            }
            total += bytes as u64;
            if total > MAX_TRANSCRIPT {
                return None;
            }
            for text in std::str::from_utf8(&line).ok()?.split('\r') {
                if !text.contains("\"tool_calls\"") && !text.contains("\"CHECKPOINT\"") {
                    continue;
                }
                let row = match PythonJson::parse_outcome(text) {
                    ParseOutcome::Value(row) => row,
                    ParseOutcome::Invalid => continue,
                    ParseOutcome::Unsupported => return None,
                };
                if Self::is_compaction(&row) {
                    covered.clear();
                    continue;
                }
                let Some(calls) = row
                    .get("tool_calls")
                    .filter(|calls| PythonJson::truthy(calls))
                else {
                    continue;
                };
                for call in calls.as_array()? {
                    let Some(raw) = Self::agy_path(call)? else {
                        continue;
                    };
                    let resolved = Path::new(&raw).canonicalize().ok()?;
                    if let Some((doc, file)) = wanted.get(&resolved) {
                        if Self::agy_read_is_current(file, row.get("created_at"))? {
                            covered.insert(*doc);
                        }
                    }
                }
            }
        }
        Some(
            docs.iter()
                .copied()
                .filter(|doc| covered.contains(doc))
                .collect(),
        )
    }

    fn agy_path(call: &Value) -> Option<Option<String>> {
        let call = call.as_object()?;
        let name = call.get("name");
        if name.is_some_and(|value| value.is_array() || value.is_object()) {
            return None;
        }
        if !matches!(
            name.and_then(Value::as_str),
            Some("read_file" | "view_file")
        ) {
            return Some(None);
        }
        let Some(arguments) = call.get("args").and_then(Value::as_object) else {
            return Some(None);
        };
        if arguments.len() != 1 {
            return Some(None);
        }
        let Some(path) = arguments.get("Path") else {
            return Some(None);
        };
        let raw = path.as_str()?;
        if raw.len() >= 2 && raw.starts_with('"') && raw.ends_with('"') {
            match PythonJson::parse_outcome(raw) {
                ParseOutcome::Value(Value::String(decoded)) => return Some(Some(decoded)),
                ParseOutcome::Unsupported => return None,
                _ => {}
            }
        }
        Some(Some(raw.into()))
    }

    fn agy_read_is_current(path: &Path, stamp: Option<&Value>) -> Option<bool> {
        let raw = match stamp {
            None | Some(Value::Null) => return Some(true),
            Some(value) => value.as_str()?,
        };
        let stamp = OverheadStamp::parse(raw)??;
        if !stamp.aware() {
            return None;
        }
        let read = (stamp.ticks() - UNIX_EPOCH_TICKS) as f64 / 1_000_000.0;
        let metadata = fs::metadata(path).ok()?;
        let modified = metadata.mtime() as f64 + 1e-9 * metadata.mtime_nsec() as f64;
        // Near floating point equality, let CPython own the timestamp rounding.
        let tolerance = f64::EPSILON * 4.0 * read.abs().max(modified.abs()).max(1.0);
        ((modified - read).abs() > tolerance).then_some(modified < read)
    }
}
