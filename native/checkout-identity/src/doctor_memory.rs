//! owner: read-only aggregation of validated project-memory records for doctor.
//! allowed imports: existing memory scan and review classifiers, JSON.
//! forbidden imports: store writes, recommendation policy and provider APIs.
//! callers/tests: doctor probe and native CLI parity fixtures.
//! verification: validated record count, expired live rows and unreadable files.
use crate::{memory_files::MemoryFiles, memory_review::MemoryReview};
use serde_json::{json, Value};

pub(super) struct DoctorMemory;

impl DoctorMemory {
    pub(super) fn summarize(payload: &Value) -> Option<Value> {
        let today = payload.get("today")?.as_str()?;
        let unicode = payload.get("unicode")?.as_str()?;
        let scan = MemoryFiles::evaluate(
            "scan",
            &json!({
                "path": payload.get("path")?.as_str()?, "unicode": unicode,
            }),
        )?;
        let records = scan.get("records")?.as_array()?;
        let review_rows = records
            .iter()
            .map(|row| json!({"id":row["id"], "status":row["status"], "review":row["review_on"]}))
            .collect::<Vec<_>>();
        // Doctor reports reached dates only. Upcoming reviews belong to the
        // full consolidation report and do not trigger a doctor warning.
        let review = MemoryReview::evaluate(
            "review-findings",
            &json!({
                "unicode": unicode, "today": today, "horizon": today,
                "records": review_rows, "statuses": payload.get("statuses")?,
            }),
        )?;
        Some(json!({
            "active_records": records.len(),
            "expired_or_due": review.get("expired")?.as_array()?.len(),
            "unreadable": scan.get("unreadable")?.as_u64()?,
        }))
    }
}
