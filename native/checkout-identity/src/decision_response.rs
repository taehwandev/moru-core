//! owner: validate prepared decision response fields and preserve original values.
//! allowed imports: bounded JSON, Python whitespace and finite arithmetic.
//! forbidden imports: provider calls, credentials, cache IO and filesystem effects.
//! callers/tests: DecisionCachePlan and test_microsoft_decision.
//! verification: first errors, original values and numeric boundary fallback.
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::collections::HashSet;

pub(crate) struct DecisionResponse;

impl DecisionResponse {
    pub(crate) fn verdict(payload: &Value) -> Option<Value> {
        match Self::validate(payload) {
            Ok(Some(keep_cost)) => Some(json!({"keep_cost": keep_cost})),
            Ok(None) => None,
            Err(error) => Some(json!({"error": error})),
        }
    }

    fn validate(payload: &Value) -> Result<Option<bool>, &'static str> {
        let response = &payload["response"];
        let model = response["model"]
            .as_str()
            .ok_or("Invalid decision response")?;
        if model.trim_matches(PythonText::whitespace).is_empty() {
            return Err("Missing response model");
        }
        let answers = response["answers"].as_object().ok_or("Missing answers")?;
        let relevant = answers
            .get("relevant")
            .filter(|value| value["type"] == "noul")
            .ok_or("Invalid relevance answer")?;
        if probability(&relevant["noul"]).is_none() {
            return Err("Invalid relevance probability");
        }
        let Some(options) = payload["options"].as_array().and_then(|values| {
            values
                .iter()
                .map(Value::as_str)
                .collect::<Option<HashSet<_>>>()
        }) else {
            return Ok(None);
        };
        let kind = answers
            .get("source_kind")
            .filter(|value| value["type"] == "choice")
            .ok_or("Invalid source classification")?;
        if kind["choice"]
            .as_str()
            .is_none_or(|choice| !options.contains(choice))
        {
            return Err("Invalid source classification");
        }
        let distribution = kind["probabilities"]
            .as_object()
            .ok_or("Invalid source classification")?;
        if distribution.len() != options.len()
            || distribution
                .keys()
                .any(|key| !options.contains(key.as_str()))
        {
            return Err("Invalid source probabilities");
        }
        let mut sum = 0.0;
        for value in distribution.values() {
            sum += probability(value).ok_or("Invalid source probabilities")?;
        }
        const TOLERANCE: f64 = 0.025;
        let delta = (sum - 1.0).abs();
        // Python versions differ in summation. Within the accumulated roundoff
        // near the boundary, keep the calling interpreter's own decision.
        let margin = f64::EPSILON * (distribution.len() as f64 + 2.0) * 4.0;
        if (delta - TOLERANCE).abs() <= margin {
            return Ok(None);
        }
        if delta > TOLERANCE {
            return Err("Source probabilities must sum to one");
        }
        let keep_cost = response["cost"]
            .as_f64()
            .is_some_and(|cost| cost.is_finite() && cost >= 0.0);
        Ok(Some(keep_cost))
    }
}

fn probability(value: &Value) -> Option<f64> {
    let number = value.as_f64()?;
    (0.0..=1.0).contains(&number).then_some(number)
}
