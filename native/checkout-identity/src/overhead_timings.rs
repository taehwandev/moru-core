//! owner: OverheadTimings; allowed imports: shared JSON/float/sum and pure stats;
//! forbidden imports: I/O, mutation and providers; callers/tests: OverheadProcess;
//! verification: skipped lines, empty-key ordering, coercions and numeric parity.
use super::overhead_stats::OverheadStats;
use crate::{
    python_float::PythonFloat,
    python_json::{Number, ParseOutcome, PythonJson, Value},
    python_sum::PythonSum,
};
use serde_json::{json, Map, Value as Json};

pub(super) struct OverheadTimings;
impl OverheadTimings {
    pub(super) fn read(text: &str) -> Option<Json> {
        let mut per_hook: Map<String, Json> = Map::new();
        let mut values: Vec<Vec<Value>> = Vec::new();
        let mut status = json!({});
        let mut records = 0u64;
        for line in text.split('\n') {
            let record = match PythonJson::parse_outcome(line) {
                ParseOutcome::Value(value) => value,
                ParseOutcome::Invalid => continue,
                ParseOutcome::Unsupported => return None,
            };
            if !record.is_object() {
                continue;
            }
            let timings = &record["timings"];
            let empty = Value::Object(crate::python_json::Object::new());
            let timings = if PythonJson::truthy(timings) {
                timings
            } else {
                &empty
            };
            let Some(mapping) = timings.as_object() else {
                continue;
            };
            let mut value = timings["hook_total"].clone();
            if matches!(value, Value::Null) && mapping.iter().next().is_some() {
                let numeric: Vec<_> = mapping
                    .iter()
                    .filter_map(|(_, value)| match value {
                        Value::Number(_) => Some(value.clone()),
                        Value::Bool(value) => Some(Value::Number(Number::Integer(
                            i32::from(*value).to_string(),
                        ))),
                        _ => None,
                    })
                    .collect();
                value = PythonSum::sum(numeric.iter())?;
            }
            let hook = PythonJson::string(&record["hook"]);
            let index = if let Some(index) = per_hook.get(&hook).and_then(Json::as_u64) {
                index as usize
            } else {
                let index = per_hook.len();
                per_hook.insert(hook.clone(), json!(index));
                values.push(Vec::new());
                index
            };
            // Subscription creates defaultdict's empty key before float(value) can fail.
            let float = match value {
                Value::Number(ref value) => Some(value.as_float()?),
                Value::Bool(value) => Some(if value { 1.0 } else { 0.0 }),
                Value::String(ref value) => PythonFloat::parse(value),
                _ => None,
            };
            let Some(float) = float else {
                continue;
            };
            if !float.is_finite() {
                return None;
            }
            values[index].push(Value::Number(Number::Float(float)));
            let key = format!("{hook}:{}", PythonJson::string(&record["status"]));
            let count = status[&key].as_u64().unwrap_or(0);
            status[&key] = json!(count + 1);
            records += 1;
        }
        for ((_, value), values) in per_hook.iter_mut().zip(values) {
            *value = OverheadStats::summarize(&values)?;
        }
        Some(json!({"records":records,"per_hook_ms":per_hook,"status":status}))
    }
}
