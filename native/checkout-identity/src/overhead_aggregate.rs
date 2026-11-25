//! owner: OverheadAggregate; allowed imports: pure stats, ordered JSON/std;
//! forbidden imports: transcript/file/state/provider I/O; callers/tests: OverheadProcess;
//! verification: group counts, exact statistics, stable Counter ties and refusal parity.
use super::overhead_stats::OverheadStats;
use crate::python_json::{Number, Object, PythonJson, Value};
use serde_json::{json, Map, Value as Json};

pub(super) struct OverheadAggregate;
impl OverheadAggregate {
    const NUMERIC: [&'static str; 16] = [
        "assistant_turns",
        "user_prompts",
        "tool_calls",
        "lifecycle_total",
        "policy_notes",
        "hook_denials",
        "moru_hook_denials",
        "stop_hook_blocks",
        "guidance_reads",
        "guidance_bash_reads",
        "tok_total",
        "tok_output",
        "tok_cache_read",
        "tok_cache_create",
        "moru_injected_tokens_est",
        "moru_injected_events",
    ];
    pub(super) fn analyze(payload: &Value) -> Option<Value> {
        let rows = payload["sessions"].as_array()?;
        let mut core = Vec::new();
        let mut other = Vec::new();
        for row in rows {
            match row["moru_core"] {
                Value::Bool(true) => core.push(row.clone()),
                Value::Bool(false) => other.push(row.clone()),
                _ => return None,
            }
        }
        let hooks = payload["hook_latency"].as_object()?;
        let mut keys: Vec<_> = hooks.iter().map(|(k, _)| k).collect();
        keys.sort();
        let mut latency = Object::new();
        for key in keys {
            latency.insert(
                key.clone(),
                OverheadStats::summarize(hooks.get(key)?.as_array()?)?,
            );
        }
        let mut result = Object::new();
        result.insert("all".into(), Self::aggregate(rows)?);
        result.insert("moru_core".into(), Self::aggregate(&core)?);
        result.insert("other_projects".into(), Self::aggregate(&other)?);
        result.insert(
            "moru_hook_latency_ms_from_transcripts".into(),
            Value::Object(latency),
        );
        Some(Value::Object(result))
    }
    pub(super) fn aggregate(rows: &[Value]) -> Option<Value> {
        let mut result = Object::new();
        result.insert(
            "sessions".into(),
            Value::Number(Number::Integer(rows.len().to_string())),
        );
        for field in Self::NUMERIC {
            let values = rows
                .iter()
                .map(|row| {
                    let value = row.get(field)?;
                    OverheadStats::integer(value)?;
                    Some(value.clone())
                })
                .collect::<Option<Vec<_>>>()?;
            result.insert(field.into(), OverheadStats::summarize(&values)?);
        }
        let mut tools = Map::new();
        let mut lifecycle = Map::new();
        for row in rows {
            Self::update(&mut tools, &row["tools"])?;
            Self::update(&mut lifecycle, &row["lifecycle_calls"])?;
        }
        result.insert(
            "tool_calls_by_name_total".into(),
            PythonJson::parse(&Self::common(&tools, 25).to_string())?,
        );
        result.insert(
            "lifecycle_calls_by_subcommand_total".into(),
            PythonJson::parse(&Self::common(&lifecycle, usize::MAX).to_string())?,
        );
        let sessions_with_lifecycle_calls = rows
            .iter()
            .filter(|row| PythonJson::truthy(&row["lifecycle_total"]))
            .count();
        result.insert(
            "sessions_with_lifecycle_calls".into(),
            Value::Number(Number::Integer(sessions_with_lifecycle_calls.to_string())),
        );
        if !rows.is_empty() {
            result.insert(
                "lifecycle_share_of_tool_calls_pct".into(),
                Self::share(
                    Self::total(rows, "lifecycle_total")?,
                    Self::total(rows, "tool_calls")?,
                )?,
            );
            result.insert(
                "guidance_read_share_of_reads_pct".into(),
                Self::share(
                    Self::total(rows, "guidance_reads")?,
                    tools.get("Read").map_or(Some(0), Json::as_i64)?,
                )?,
            );
            result.insert(
                "injected_tokens_vs_new_input_pct".into(),
                Self::share(
                    Self::total(rows, "moru_injected_tokens_est")?,
                    Self::total(rows, "tok_input")?
                        .checked_add(Self::total(rows, "tok_cache_create")?)?,
                )?,
            );
        }
        Some(Value::Object(result))
    }
    fn total(rows: &[Value], field: &str) -> Option<i64> {
        rows.iter().try_fold(0i64, |sum, row| {
            sum.checked_add(OverheadStats::integer(row.get(field)?)?)
        })
    }
    fn share(numerator: i64, denominator: i64) -> Option<Value> {
        let numerator = numerator.checked_mul(100)?;
        if numerator.unsigned_abs() > (1u64 << 53) || denominator.unsigned_abs() > (1u64 << 53) {
            return None;
        }
        OverheadStats::rounded(
            numerator as f64
                / if denominator == 0 {
                    1.0
                } else {
                    denominator as f64
                },
        )
    }
    fn update(counter: &mut Map<String, Json>, value: &Value) -> Option<()> {
        for (key, value) in value.as_object()?.iter() {
            let count = OverheadStats::integer(value)?;
            let prior = counter.get(key).map_or(Some(0), Json::as_i64)?;
            counter.insert(key.into(), json!(prior.checked_add(count)?));
        }
        Some(())
    }
    fn common(counter: &Map<String, Json>, limit: usize) -> Json {
        let mut values: Vec<_> = counter.iter().collect();
        values.sort_by(|a, b| b.1.as_i64().cmp(&a.1.as_i64()));
        Json::Object(
            values
                .into_iter()
                .take(limit)
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
        )
    }
}
