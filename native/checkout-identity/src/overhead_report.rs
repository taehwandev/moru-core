//! owner: OverheadReport; allowed imports: CLI/clock, collection, aggregation, timing reader;
//! forbidden imports: providers, state/output writes; callers/tests: report command;
//! verification: complete report shape, partitioning, notes, source counts and chronology.
use crate::{
    overhead_aggregate::OverheadAggregate, overhead_cli::OverheadCli,
    overhead_clock::OverheadClock, overhead_collection::OverheadCollection,
    overhead_process::OverheadProcess, overhead_timings::OverheadTimings, python_json::PythonJson,
    text::Text,
};
use serde_json::{json, Value};
use std::path::Path;

pub(crate) struct OverheadReport;
impl OverheadReport {
    pub(crate) fn build(args: &OverheadCli) -> Option<Value> {
        let clock = OverheadClock::new(args.since.as_deref(), args.until.as_deref(), args.days)?;
        let roots: Vec<_> = std::iter::once(&args.moru_root)
            .chain(args.alias_root.iter())
            .filter(|s| !s.is_empty())
            .map(|s| s.trim_end_matches('/').to_owned())
            .collect();
        let collection = OverheadCollection::read(args, &roots, &clock)?;
        let payload = json!({"sessions":collection.sessions,"hook_latency":collection.shared["hook_latency"]});
        let analysis = OverheadAggregate::analyze(&PythonJson::parse(&payload.to_string())?)?;
        let mut result = json!({"generated_at":clock.now,"window":{"since":clock.window()[0],"until":clock.window()[1]},
            "sources":{"transcript_files_in_window":collection.sessions.len(),"include_subagents":args.include_subagents},
            "notes":"tokens sum input, cache read, cache creation and output per unique assistant message; moru_injected_tokens_est is chars/4 of Moru hook context, plain-text hook stdout and Moru PreToolUse denial reasons, an approximation rather than a tokenizer count."});
        for (key, value) in analysis.as_object()? {
            result[key] = value.clone();
        }
        result["timings_jsonl"] = if Path::new(&args.timings).exists() {
            let bytes = OverheadProcess::read(&args.timings)?;
            OverheadTimings::read(&Text::universal_newlines(&String::from_utf8_lossy(&bytes)))?
        } else {
            OverheadTimings::read("")?
        };
        result["top_policy_notes"] = Self::common(&collection.shared["notes"])?;
        result["top_hook_denials"] = Self::common(&collection.shared["denials"])?;
        Some(result)
    }
    fn common(counter: &Value) -> Option<Value> {
        let mut items: Vec<_> = counter.as_object()?.iter().collect();
        items.sort_by(|a, b| b.1.as_i64().cmp(&a.1.as_i64()));
        Some(Value::Array(
            items
                .into_iter()
                .take(5)
                .map(|(message, count)| json!({"count":count,"message":message}))
                .collect(),
        ))
    }
}
