//! owner: MemoryProcess; allowed imports: std/JSON/source guard/read-only memory owners;
//! forbidden imports: direct store IO, writes, providers; callers/tests: private
//! native protocol; verification: source/transport/schema/empty-PATH checks.
use crate::{
    memory_analysis::MemoryAnalysis, memory_consolidation::MemoryConsolidation,
    memory_files::MemoryFiles, memory_history::MemoryHistory, memory_recall::MemoryRecall,
    memory_review::MemoryReview, memory_source::MemorySource, memory_status::MemoryStatus,
    memory_upkeep::MemoryUpkeep, pretool_guard::CallbackGuard,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
};
pub(crate) struct MemoryProcess;
impl MemoryProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2 || CallbackGuard::root(launcher, "memory-probe").is_none() {
            return 125;
        }
        let Some(operation) = args[1].to_str() else {
            return 125;
        };
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        let Some(result) = serde_json::from_slice::<Value>(&bytes)
            .ok()
            .and_then(|payload| {
                if matches!(operation, "review-partition" | "review-findings") {
                    MemoryReview::evaluate(operation, &payload)
                } else if matches!(
                    operation,
                    "upkeep-live"
                        | "upkeep-replacements"
                        | "upkeep-startup"
                        | "upkeep-startup-dates"
                ) {
                    MemoryUpkeep::evaluate(operation, &payload)
                } else if matches!(operation, "duplicate-groups" | "shared-source-groups") {
                    MemoryConsolidation::evaluate(operation, &payload)
                } else if matches!(operation, "analysis-binding" | "analysis-candidates") {
                    MemoryAnalysis::evaluate(operation, &payload)
                } else if operation == "history" {
                    MemoryHistory::evaluate(&payload)
                } else if operation == "source-status" {
                    MemoryStatus::evaluate(&payload)
                } else if operation == "blob" {
                    MemorySource::evaluate(&payload)
                } else if matches!(operation, "record" | "scan") {
                    MemoryFiles::evaluate(operation, &payload)
                } else {
                    MemoryRecall::evaluate(operation, &payload)
                }
            })
        else {
            return 125;
        };
        let Ok(mut bytes) = serde_json::to_vec(&json!({"schema_version":1,"result":result})) else {
            return 125;
        };
        bytes.push(b'\n');
        if std::io::stdout().write_all(&bytes).is_ok() {
            0
        } else {
            1
        }
    }
}
