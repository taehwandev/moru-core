//! owner: synthetic experience record preparation; allowed imports: existing
//! calendar arithmetic and canonical memory digest; forbidden imports: file
//! I/O, store writes, engine selection and ranking; callers/tests: private
//! memory probe and byte-for-byte Python preparation parity.
use crate::{memory_json::MemoryJson, overhead_clock::OverheadClock};
use serde_json::{json, Value};

pub(super) struct ExperienceRecords;

impl ExperienceRecords {
    pub(super) fn evaluate(payload: &Value) -> Option<Value> {
        let fields = payload.as_object()?;
        if fields.len() != 2 {
            return None;
        }
        let today = fields.get("today")?.as_str()?;
        let records: Vec<_> = fields
            .get("records")?
            .as_array()?
            .iter()
            .map(|item| Self::prepare(item, today))
            .collect::<Option<_>>()?;
        Some(json!({"records": records}))
    }

    fn prepare(item: &Value, today: &str) -> Option<Value> {
        let mut record = item.as_object()?.clone();
        // Ordered removal keeps the original field order used when rendering.
        let days = match record.shift_remove("review_in_days") {
            Some(days) => days.as_i64()?,
            None => 30,
        };
        let review_on = OverheadClock::date_plus_days(today, days)?;
        record.insert("schema_version".into(), 1.into());
        record.entry("status").or_insert_with(|| "active".into());
        record.entry("scope").or_insert_with(|| "task".into());
        record.insert(
            "created_at".into(),
            format!("{today}T00:00:00+00:00").into(),
        );
        record.insert("review_on".into(), review_on.into());
        let mut prepared = Value::Object(record);
        let digest = MemoryJson::digest(&prepared)?;
        prepared["digest"] = digest.into();
        Some(prepared)
    }
}
