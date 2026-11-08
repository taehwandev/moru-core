//! owner: OverheadAggregate; allowed imports: pure stats, ordered JSON/std;
//! forbidden imports: transcript/file/state/provider I/O; callers/tests: OverheadProcess;
//! verification: group counts, exact statistics, stable Counter ties and refusal parity.
use super::overhead_stats::OverheadStats;
use crate::python_json::{PythonJson, Value};
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
    pub(super) fn analyze(payload: &Value) -> Option<Json> {
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
        let mut latency = json!({});
        for key in keys {
            latency[key] = OverheadStats::summarize(hooks.get(key)?.as_array()?)?;
        }
        Some(
            json!({"all":Self::aggregate(rows)?,"moru_core":Self::aggregate(&core)?,
            "other_projects":Self::aggregate(&other)?,
            "moru_hook_latency_ms_from_transcripts":latency}),
        )
    }
    pub(super) fn aggregate(rows: &[Value]) -> Option<Json> {
        let mut result = json!({"sessions":rows.len()});
        for field in Self::NUMERIC {
            let values = rows
                .iter()
                .map(|row| {
                    let value = row.get(field)?;
                    OverheadStats::integer(value)?;
                    Some(value.clone())
                })
                .collect::<Option<Vec<_>>>()?;
            result[field] = OverheadStats::summarize(&values)?;
        }
        let mut tools = Map::new();
        let mut lifecycle = Map::new();
        for row in rows {
            Self::update(&mut tools, &row["tools"])?;
            Self::update(&mut lifecycle, &row["lifecycle_calls"])?;
        }
        result["tool_calls_by_name_total"] = Self::common(&tools, 25);
        result["lifecycle_calls_by_subcommand_total"] = Self::common(&lifecycle, usize::MAX);
        result["sessions_with_lifecycle_calls"] = json!(rows
            .iter()
            .filter(|row| PythonJson::truthy(&row["lifecycle_total"]))
            .count());
        if !rows.is_empty() {
            result["lifecycle_share_of_tool_calls_pct"] = Self::share(
                Self::total(rows, "lifecycle_total")?,
                Self::total(rows, "tool_calls")?,
            )?;
            result["guidance_read_share_of_reads_pct"] = Self::share(
                Self::total(rows, "guidance_reads")?,
                tools.get("Read").map_or(Some(0), Json::as_i64)?,
            )?;
            result["injected_tokens_vs_new_input_pct"] = Self::share(
                Self::total(rows, "moru_injected_tokens_est")?,
                Self::total(rows, "tok_input")?
                    .checked_add(Self::total(rows, "tok_cache_create")?)?,
            )?;
        }
        Some(result)
    }
    fn total(rows: &[Value], field: &str) -> Option<i64> {
        rows.iter().try_fold(0i64, |sum, row| {
            sum.checked_add(OverheadStats::integer(row.get(field)?)?)
        })
    }
    fn share(numerator: i64, denominator: i64) -> Option<Json> {
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
