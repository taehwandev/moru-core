//! owner: deterministic merge and staleness for a lesson compaction plan.
//! allowed imports: shared Python JSON and calendar parsing, standard collections.
//! forbidden imports: filesystem, locks and authority decisions.
//! callers/tests: lessons-compact plan and test_lessons_compact.
//! verification: tie order, integer total, key cap, calendar buckets and strict stale boundary.
use crate::{
    overhead_stamp::OverheadStamp,
    python_json::{Number, Object, PythonJson, Value},
};
use serde_json::{json, Value as Json};
use std::collections::{BTreeMap, HashSet};

pub(super) struct LessonCompactionMerge;

impl LessonCompactionMerge {
    const DAY: i64 = 86_400_000_000;

    pub(super) fn probe(input: &Json) -> Option<Json> {
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let keys: usize = input.get("key_limit")?.as_u64()?.try_into().ok()?;
        let recent = input.get("recent_days")?.as_i64()?.checked_sub(1)?;
        if keys == 0 || recent < 0 {
            return None;
        }
        let cutoff = match input.get("now")? {
            Json::Null => None,
            value => {
                let now = OverheadStamp::parse(value.as_str()?)??;
                let stale = input.get("stale_days")?.as_i64()?.checked_mul(Self::DAY)?;
                if !now.aware() || stale < 0 {
                    return None;
                }
                Some(now.ticks().checked_sub(stale)?)
            }
        };
        let groups = PythonJson::parse_with_diagnostic(
            input.get("groups_json")?.as_str()?,
            Some(limit),
            None,
        )
        .ok()??;
        let mut plans = Vec::new();
        for group in groups.as_array()? {
            let records = group.as_array()?;
            let merged = Self::merge(records, keys, recent)?;
            let is_stale = match cutoff {
                Some(cutoff) if merged["status"].as_str() != Some("stale") => {
                    OverheadStamp::parse(&Self::text(&merged, &["last_seen_at", "created_at"]))?
                        .is_some_and(|seen| seen.ticks() < cutoff)
                }
                _ => false,
            };
            plans.push((PythonJson::render(&merged, false, true)?, is_stale));
        }
        Some(json!({"plans": plans}))
    }

    fn merge(records: &[Value], limit: usize, recent_days: i64) -> Option<Value> {
        let mut records: Vec<_> = records.iter().collect();
        records.sort_by_cached_key(|record| Self::text(record, &["created_at"]));
        let mut merged = records.last()?.as_object()?.clone();
        let mut count = 0i64;
        let mut keys = Vec::new();
        let mut seen = HashSet::new();
        let mut recent = BTreeMap::new();
        let mut has_recent = false;
        for record in &records {
            record.as_object()?;
            let occurrences = match record.get("occurrence_count") {
                None => 1,
                Some(Value::Number(Number::Integer(value))) => value.parse::<i64>().ok()?.max(1),
                _ => 0,
            };
            count = count.checked_add(occurrences)?;
            if let Some(values) = record.get("occurrence_keys") {
                for key in values.as_array()?.iter().filter_map(Value::as_str) {
                    if !key.is_empty() && seen.insert(key) {
                        keys.push(Value::String(key.to_owned()));
                    }
                }
            }
            if let Some(buckets) = record["recent_occurrences"].as_object() {
                has_recent = true;
                for (day, value) in buckets.iter() {
                    if day.chars().count() != 10 {
                        continue;
                    }
                    let Some(date) = OverheadStamp::parse(day)? else {
                        continue;
                    };
                    if let Value::Number(Number::Integer(value)) = value {
                        let count: i64 = value.parse().ok()?;
                        if count > 0 {
                            let entry = recent.entry(day.clone()).or_insert((date.ticks(), 0i64));
                            entry.1 = entry.1.checked_add(count)?;
                        }
                    }
                }
            }
        }
        let first = records
            .iter()
            .map(|r| Self::text(r, &["first_seen_at", "created_at"]))
            .min()?;
        let last = records
            .iter()
            .map(|r| Self::text(r, &["last_seen_at", "created_at"]))
            .max()?;
        merged.insert("first_seen_at".into(), Value::String(first));
        merged.insert("last_seen_at".into(), Value::String(last));
        merged.insert("occurrence_count".into(), Self::integer(count));
        merged.insert(
            "occurrence_keys".into(),
            Value::Array(keys.split_off(keys.len().saturating_sub(limit))),
        );
        if has_recent {
            let mut buckets = Object::new();
            if let Some((_, (anchor, _))) = recent.last_key_value() {
                let cutoff = anchor.checked_sub(recent_days.checked_mul(Self::DAY)?)?;
                // Python date subtraction fails when the cutoff predates year one.
                if cutoff < Self::DAY {
                    return None;
                }
                for (day, (tick, count)) in recent {
                    if tick >= cutoff {
                        buckets.insert(day, Self::integer(count));
                    }
                }
            }
            merged.insert("recent_occurrences".into(), Value::Object(buckets));
        }
        Some(Value::Object(merged))
    }

    fn text(record: &Value, keys: &[&str]) -> String {
        keys.iter()
            .filter_map(|key| record.get(key))
            .find(|value| PythonJson::truthy(value))
            .map(PythonJson::string)
            .unwrap_or_default()
    }

    fn integer(value: i64) -> Value {
        Value::Number(Number::Integer(value.to_string()))
    }
}
