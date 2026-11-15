//! owner: MemoryAnalysis; allowed imports: serde_json, std, MemoryRecall, MemoryTerms, PythonText;
//! forbidden imports: filesystem, processes, stores, writes, providers, clock, authority;
//! callers/tests: MemoryProcess analysis dispatch and memory_analysis_tests;
//! verification: Python _analysis_binding and _analysis_recall candidate parity.
use crate::{memory_recall::MemoryRecall, memory_terms::MemoryTerms, python_text::PythonText};
use serde_json::{json, Value};

const MAX_ANALYSIS_CHARS: usize = 300;

pub(crate) struct MemoryAnalysis;

impl MemoryAnalysis {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        match operation {
            "analysis-binding" => Self::binding(payload),
            "analysis-candidates" => Self::candidates(payload),
            "analysis-recall" => Self::shortlist(payload),
            _ => None,
        }
    }

    fn shortlist(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 5 {
            return None;
        }
        let binding = object.get("binding")?;
        let scope = object.get("scope")?;
        let records = object.get("records")?.as_array()?;
        let mut recall = payload.clone();
        let fields = recall.as_object_mut()?;
        fields.remove("binding");
        fields.insert("context".to_owned(), json!(""));
        let selected = MemoryRecall::evaluate("recall", &recall)?;
        let indices = selected.get("indices")?.as_array()?;
        let mut rows = Vec::with_capacity(indices.len());
        for index in indices {
            let record = records.get(usize::try_from(index.as_u64()?).ok()?)?;
            let analysis = match record.get("analysis") {
                None => Value::Null,
                Some(value) => {
                    let fields = value.as_object()?;
                    json!({"question":fields.get("question"),"context":fields.get("context")})
                }
            };
            rows.push(json!({"scope":record.get("scope")?,"analysis":analysis}));
        }
        let candidates = Self::candidates(&json!({
            "unicode":object.get("unicode")?,"scope":scope,"binding":binding,"records":rows
        }))?;
        let mut result = Vec::new();
        for index in candidates.get("indices")?.as_array()? {
            result.push(indices.get(usize::try_from(index.as_u64()?).ok()?)?.clone());
        }
        Some(json!({"indices":result}))
    }

    fn binding(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 3 || object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let question = object.get("question")?.as_str()?;
        let context = object.get("context")?.as_str()?;
        if question.is_empty() && context.is_empty() {
            return Some(json!({ "binding": null }));
        }
        let (Some(question), Some(context)) =
            (Self::clean_line(question), Self::clean_line(context))
        else {
            return Some(json!({ "invalid": true }));
        };
        Some(json!({
            "binding": {
                "question": question,
                "context": context,
            }
        }))
    }

    fn candidates(payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.len() != 4 || object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let scope = object.get("scope")?.as_str()?;
        let binding = object.get("binding")?.as_object()?;
        if binding.len() != 2 {
            return None;
        }
        let question = binding.get("question")?.as_str()?;
        let context = binding.get("context")?.as_str()?;
        let records = object.get("records")?.as_array()?;
        let mut indices = Vec::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            let row_scope = row.get("scope")?.as_str()?;
            let matched = match row.get("analysis")? {
                Value::Null => false,
                Value::Object(analysis) if analysis.len() == 2 => {
                    let row_question = Self::nullable_str(analysis.get("question")?)?;
                    let row_context = Self::nullable_str(analysis.get("context")?)?;
                    row_scope == scope
                        && row_question == Some(question)
                        && row_context == Some(context)
                }
                _ => return None,
            };
            if matched {
                indices.push(index);
            }
        }
        Some(json!({ "indices": indices }))
    }

    fn clean_line(value: &str) -> Option<&str> {
        let mut count = 0;
        for character in value.chars() {
            count += 1;
            if count > MAX_ANALYSIS_CHARS || !PythonText::printable(character) {
                return None;
            }
        }
        let trimmed = value.trim_matches(PythonText::whitespace);
        (!trimmed.is_empty()).then_some(trimmed)
    }

    fn nullable_str(value: &Value) -> Option<Option<&str>> {
        match value {
            Value::Null => Some(None),
            Value::String(text) => Some(Some(text.as_str())),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "memory_analysis_tests.rs"]
mod tests;
