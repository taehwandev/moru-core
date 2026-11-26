//! Owner: aggregate status trend report assembly.
//! Allowed imports: the existing trend summaries, Python text compatibility and JSON.
//! Forbidden: state, clocks, filesystem access and session identifiers.
//! Callers/tests: StatusTrends and the observability report parity fixture.
use super::StatusTrends;
use crate::python_text::PythonText;
use serde_json::{json, Value};

pub(super) fn assemble(request: &Value) -> Option<Value> {
    let runs = request.get("runs")?.as_array()?;
    let month = request
        .get("month")?
        .as_str()?
        .trim_matches(PythonText::whitespace);
    let project_count = request.get("project_count")?.as_u64()?;
    let mut session_bound = 0;
    let mut fresh = 0;
    let mut continuation = 0;
    let mut matched = Vec::new();
    for run in runs {
        session_bound += usize::from(run.get("session_bound")?.as_bool()?);
        let turns = run.get("turns")?.as_i64()?;
        let mode = run.get("same_work_mode")?.as_str()?;
        if turns > 0 {
            matched.push(run);
            fresh += usize::from(mode == "fresh");
            continuation += usize::from(mode == "continuation");
        }
    }
    let matched_count = matched.len();
    let coverage = if session_bound == 0 {
        0.0
    } else {
        StatusTrends::rounded(matched_count as f64 / session_bound as f64, 4)?
    };
    let mut report = StatusTrends::summarize(&json!({"matched": matched}))?;
    let fields = report.as_object_mut()?;
    fields.insert("schema_version".into(), json!(1));
    fields.insert(
        "month_filter".into(),
        json!(if month.is_empty() { "all" } else { month }),
    );
    fields.insert("project_count".into(), json!(project_count));
    fields.insert("total_runs".into(), json!(runs.len()));
    fields.insert("session_bound_runs".into(), json!(session_bound));
    fields.insert("spill_matched_runs".into(), json!(matched_count));
    fields.insert("binding_coverage_ratio".into(), json!(coverage));
    fields.insert("fresh_runs".into(), json!(fresh));
    fields.insert("continuation_runs".into(), json!(continuation));
    Some(report)
}
