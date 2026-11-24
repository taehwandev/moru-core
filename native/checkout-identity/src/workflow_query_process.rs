//! owner: prepared workflow search probes and plain-text reports.
//! allowed imports: bounded JSON transport, source guards and string formatting.
//! forbidden imports: retrieval, project writes and vendor source.
//! callers/tests: workflow_search.py and workflow query process parity.
//! verification: empty, ordinary, decorated and unsupported report inputs.
use crate::{pretool_guard::CallbackGuard, workflow_wikimap_rank::WikimapRank};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fmt::Write as _,
    io::{self, Read, Write},
};

const MAX_MESSAGE: usize = 1024 * 1024;

pub(crate) struct WorkflowQueryProcess;

impl WorkflowQueryProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || !matches!(args[1].to_str(), Some("render-text" | "rank-wikimap"))
            || CallbackGuard::root(launcher, "workflow-query-text").is_none()
        {
            return 125;
        }
        let mut message = Vec::new();
        if io::stdin()
            .take((MAX_MESSAGE + 1) as u64)
            .read_to_end(&mut message)
            .is_err()
            || message.len() > MAX_MESSAGE
        {
            return 125;
        }
        let Some(result) =
            serde_json::from_slice(&message)
                .ok()
                .and_then(|payload| match args[1].to_str()? {
                    "render-text" => Self::format(&payload).map(|text| json!({"text": text})),
                    "rank-wikimap" => {
                        WikimapRank::rank(&payload).map(|results| json!({"results": results}))
                    }
                    _ => None,
                })
        else {
            return 125;
        };
        let Ok(response) = serde_json::to_vec(&json!({"schema_version": 1, "result": result}))
        else {
            return 125;
        };
        if response.len() > MAX_MESSAGE {
            return 125;
        }
        i32::from(io::stdout().write_all(&response).is_err())
    }

    fn format(payload: &Value) -> Option<String> {
        let query = payload.get("query")?.as_str()?;
        let results = payload.get("results")?.as_array()?;
        let mut output = format!("# Moru Core Document Query: \"{query}\"\n\n");
        let Some(first) = results.first() else {
            output.push_str(
                "No matching documents found.\n\nTry broader terms or run `workflow.py list` to browse available concerns.\n",
            );
            return Some(output);
        };
        let backend = text(first.get("search_backend"))?;
        if !backend.is_empty() {
            writeln!(output, "Backend: {backend}\n").ok()?;
        }
        writeln!(output, "Top {} result(s):\n", results.len()).ok()?;
        for item in results {
            Self::row(&mut output, item)?;
            if output.len() > MAX_MESSAGE {
                return None;
            }
        }
        output.push_str("\nTo get a structured route:\n  python3 <MORU_ROOT>/scripts/workflow.py route <command> --request \"<request>\"\n");
        Some(output)
    }

    fn row(output: &mut String, item: &Value) -> Option<()> {
        let path = item.get("path")?.as_str()?;
        let description = text(item.get("description"))?;
        let title = text(item.get("title"))?;
        let label = [description, title, path]
            .into_iter()
            .find(|s| !s.is_empty())
            .unwrap_or(path);
        write!(output, "- `{path}").ok()?;
        match item.get("line") {
            Some(line) if line.as_i64() == Some(0) => {}
            Some(line) if line.is_i64() || line.is_u64() => write!(output, ":{line}").ok()?,
            None | Some(Value::Null | Value::Bool(false)) => {}
            _ => return None,
        }
        write!(output, "` — {label}").ok()?;
        for (key, prefix, limit) in [
            ("matched_facets", "matched facets", usize::MAX),
            ("graph_reasons", "graph", 2),
        ] {
            let Some(value) = item.get(key).filter(|value| !value.is_null()) else {
                continue;
            };
            let fields: Vec<_> = value
                .as_array()?
                .iter()
                .take(limit)
                .map(Value::as_str)
                .collect::<Option<_>>()?;
            if !fields.is_empty() {
                write!(output, " ({prefix}: {})", fields.join(", ")).ok()?;
            }
        }
        let heading = text(item.get("heading"))?;
        if !heading.is_empty() {
            write!(output, " (section: {heading})").ok()?;
        }
        output.push('\n');
        Some(())
    }
}

fn text(value: Option<&Value>) -> Option<&str> {
    match value {
        None | Some(Value::Null | Value::Bool(false)) => Some(""),
        Some(value) => value.as_str(),
    }
}
