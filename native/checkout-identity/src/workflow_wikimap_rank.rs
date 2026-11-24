//! owner: fuse ordered Wikimap matches and Moru policy boosts.
//! allowed imports: only prepared JSON and in-memory ranking.
//! forbidden imports: filesystem, vendor source, retrieval, and authority.
//! callers/tests: WorkflowQueryProcess; test_workflow_query_text.
//! verification: first-match metadata, ordering, slicing and Python fallback.
use serde_json::{json, Value};
use std::collections::HashMap;

pub(crate) struct WikimapRank;

impl WikimapRank {
    pub(crate) fn rank(payload: &Value) -> Option<Vec<Value>> {
        let docs = payload.get("documents")?.as_object()?;
        let matches = payload.get("matches")?.as_array()?;
        let boosts = payload.get("boosts")?.as_object()?;
        let rank_base = payload.get("rank_base")?.as_i64()?;
        let policy_base = payload.get("policy_base")?.as_i64()?;
        let limit = payload.get("limit")?.as_i64()?;
        let mut ranked = HashMap::new();
        for (index, hit) in matches.iter().enumerate() {
            let path = hit.get("path")?.as_str()?;
            if ranked.contains_key(path) {
                continue;
            }
            let Some(document) = docs.get(path) else {
                continue;
            };
            let score = rank_base.checked_sub(i64::try_from(index).ok()?)?;
            ranked.insert(path, (score, Self::matched(document, hit, score)?));
        }
        for (path, boost) in boosts {
            let Some(document) = docs.get(path) else {
                continue;
            };
            let entry = ranked
                .entry(path.as_str())
                .or_insert_with(|| (0, document.clone()));
            entry.0 = entry.0.max(policy_base.checked_add(boost.as_i64()?)?);
            let fields = entry.1.as_object_mut()?;
            fields.insert("score".into(), json!(entry.0));
            fields.insert("search_backend".into(), json!("wikimap"));
        }
        let mut rows: Vec<_> = ranked.into_iter().collect();
        rows.sort_unstable_by(|(path_a, (score_a, _)), (path_b, (score_b, _))| {
            score_b.cmp(score_a).then_with(|| path_a.cmp(path_b))
        });
        let count = usize::try_from(limit.unsigned_abs()).unwrap_or(usize::MAX);
        let end = if limit < 0 {
            rows.len().saturating_sub(count)
        } else {
            count
        };
        Some(
            rows.into_iter()
                .take(end)
                .map(|(_, (_, row))| row)
                .collect(),
        )
    }

    fn matched(document: &Value, hit: &Value, score: i64) -> Option<Value> {
        let mut row = document.as_object()?.clone();
        let line = match hit.get("line") {
            None | Some(Value::Null | Value::Bool(false)) => 0,
            Some(line) => line.as_i64()?,
        };
        let heading = string(hit.get("heading"))?;
        let sources = string(hit.get("sources"))?;
        let matched = match hit.get("matched") {
            None | Some(Value::Null | Value::Bool(false)) => json!([]),
            Some(values) if values.is_array() => values.clone(),
            _ => return None,
        };
        row.insert("score".into(), json!(score));
        row.insert("search_backend".into(), json!("wikimap"));
        row.insert("line".into(), json!(line));
        row.insert("heading".into(), json!(heading));
        row.insert("matched_lines".into(), matched);
        row.insert("rank_sources".into(), json!(sources));
        Some(Value::Object(row))
    }
}

fn string(value: Option<&Value>) -> Option<&str> {
    match value {
        None | Some(Value::Null | Value::Bool(false)) => Some(""),
        Some(value) => value.as_str(),
    }
}
