//! owner: pure required-document delivery text;
//! allowed imports: JSON, Python-compatible whitespace, and std strings;
//! forbidden imports: file, marker, provider and admission operations;
//! callers/tests: private doc-transcript probe and required-doc differential tests;
//! verification: leading header, UTF-8 limits, ordering and empty delivery.
use crate::python_text::PythonText;
use serde_json::Value;

pub(super) struct DocDeliveryText;

impl DocDeliveryText {
    pub(super) fn render(payload: &Value) -> Option<String> {
        let inline_limit = payload.get("inline_limit")?.as_u64()?;
        let total_limit = payload.get("total_limit")?.as_u64()?;
        let mut inline = Vec::new();
        let mut listed = Vec::new();
        let mut used = 0u64;
        for doc in payload.get("docs")?.as_array()? {
            let name = doc.get("name")?.as_str()?;
            let raw = doc.get("text")?.as_str()?;
            let text = raw
                .strip_prefix("---\n")
                .and_then(|body| body.split_once("\n---\n"))
                .map_or(raw, |(_, text)| text)
                .trim_matches(PythonText::whitespace);
            let bytes = text.len() as u64;
            if bytes <= inline_limit && used.checked_add(bytes)? <= total_limit {
                inline.push(format!("=== {name} ===\n{text}"));
                used += bytes;
            } else {
                let path = doc.get("path")?.as_str()?;
                listed.push(format!("{path} ({bytes} bytes)"));
            }
        }
        if inline.is_empty() && listed.is_empty() {
            return Some(String::new());
        }
        let mut parts = vec!["Moru required docs not yet read in this run, delivered once before its first edit. Apply them to this change; this does not block the edit.".into()];
        if !listed.is_empty() {
            parts.push(format!("Read each of these whole, with no line range, before continuing (too large to include; a ranged read does not count as read): {}", listed.join("; ")));
        }
        parts.extend(inline);
        Some(parts.join("\n\n"))
    }
}
