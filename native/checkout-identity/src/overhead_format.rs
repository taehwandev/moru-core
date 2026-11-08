//! owner: OverheadFormat; allowed imports: lossless JSON values and pure report formatter;
//! forbidden imports: I/O, writes, Python processes; callers/tests: overhead format probe;
//! verification: lossless numeric text parity and malformed/container refusal.
use crate::{
    overhead_report_text::OverheadReportText,
    python_json::{PythonJson, Value},
};
use serde_json::{json, Value as Json};
pub(crate) struct OverheadFormat;
impl OverheadFormat {
    pub(crate) fn format(payload: &Value) -> Option<Json> {
        // The transport envelope remains strict JSON. Report text may contain
        // Python's NaN/Infinity tokens without widening any other probe.
        let decoded;
        let report = if let Some(raw) = payload.get("report_json") {
            decoded = PythonJson::parse(raw.as_str()?)?;
            &decoded
        } else {
            payload.get("report")?
        };
        let text = match payload["format"].as_str()? {
            "json" => OverheadReportText::json_value(report)?,
            "markdown" => OverheadReportText::markdown_value(report)?,
            _ => return None,
        };
        Some(json!({"text":text}))
    }
}
