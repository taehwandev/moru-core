//! owner: OverheadCollection; allowed imports: guarded reader/session tally, clock, std/JSON;
//! forbidden imports: writes, providers, shell execution; callers/tests: report construction;
//! verification: glob order, hidden/excluded files, subagents and pre-filter shared counters.
use crate::{
    overhead_cli::OverheadCli, overhead_clock::OverheadClock, overhead_process::OverheadProcess,
    overhead_session::OverheadSession, text::Text,
};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};

pub(crate) struct OverheadCollection {
    pub(crate) sessions: Vec<Value>,
    pub(crate) shared: Value,
}
impl OverheadCollection {
    pub(crate) fn read(
        args: &OverheadCli,
        roots: &[String],
        clock: &OverheadClock,
    ) -> Option<Self> {
        if args.projects_dir.contains(['*', '?', '[']) {
            return None;
        }
        let base = Path::new(if args.projects_dir.is_empty() {
            "."
        } else {
            &args.projects_dir
        });
        let mut files = Vec::new();
        for project in Self::entries(base, true)? {
            files.extend(
                Self::entries(&project, false)?
                    .into_iter()
                    .filter(|p| p.extension().is_some_and(|s| s == "jsonl")),
            );
        }
        if args.include_subagents {
            for project in Self::entries(base, true)? {
                for session in Self::entries(&project, true)? {
                    files.extend(
                        Self::entries(&session.join("subagents"), false)?
                            .into_iter()
                            .filter(|p| p.extension().is_some_and(|s| s == "jsonl")),
                    );
                }
            }
        }
        let mut result = Self {
            sessions: Vec::new(),
            shared: json!({"notes":{},"denials":{},"hook_latency":{}}),
        };
        let window = clock.window();
        for path in files {
            let metadata = match fs::metadata(&path) {
                Ok(value) => value,
                Err(_) => continue,
            };
            let name = path.file_name()?.to_str()?;
            if !clock.includes_mtime(&metadata)?
                || args.exclude_session.iter().any(|skip| name.contains(skip))
            {
                continue;
            }
            let bytes = OverheadProcess::read(path.to_str()?)?;
            let text = Text::universal_newlines(&String::from_utf8_lossy(&bytes));
            let measured = OverheadSession::measure(path.to_str()?, &text, roots, &window)?;
            result.merge(&measured["shared"])?;
            if measured["row"]["assistant_turns"].as_i64()? >= args.min_turns {
                result.sessions.push(measured["row"].clone());
            }
        }
        Some(result)
    }
    fn entries(path: &Path, directories: bool) -> Option<Vec<PathBuf>> {
        let entries = match fs::read_dir(path) {
            Ok(entries) => entries,
            Err(_) => return Some(Vec::new()),
        };
        let mut result = Vec::new();
        for entry in entries {
            let entry = entry.ok()?;
            let name = entry.file_name();
            if name.to_str()?.starts_with('.') {
                continue;
            }
            if !directories || entry.path().is_dir() {
                result.push(entry.path());
            }
        }
        Some(result)
    }
    fn merge(&mut self, delta: &Value) -> Option<()> {
        for name in ["notes", "denials"] {
            for (key, value) in delta[name].as_object()? {
                let count = self.shared[name][key]
                    .as_i64()
                    .unwrap_or(0)
                    .checked_add(value.as_i64()?)?;
                self.shared[name][key] = json!(count);
            }
        }
        for (key, values) in delta["hook_latency"].as_object()? {
            if self.shared["hook_latency"].get(key).is_none() {
                self.shared["hook_latency"][key] = json!([]);
            }
            self.shared["hook_latency"][key]
                .as_array_mut()?
                .extend_from_slice(values.as_array()?);
        }
        Some(())
    }
}
