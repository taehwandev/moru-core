//! owner: score prepared offline document search fields.
//! allowed imports: bounded JSON values and integer scoring.
//! forbidden imports: filesystem, retrieval, permission checks, vendor code.
//! callers/tests: WorkflowQueryProcess; test_workflow_query_text.
//! verification: weighted field presence, signed boosts and compatibility.
use serde_json::Value;

pub(crate) struct OfflineScore;

impl OfflineScore {
    pub(crate) fn batch(payload: &Value) -> Option<Vec<i64>> {
        let groups = [terms(payload, "raw")?, terms(payload, "expanded")?];
        payload
            .get("rows")?
            .as_array()?
            .iter()
            .map(|row| {
                let [boost, fields] = row.as_array()?.as_slice() else {
                    return None;
                };
                let [description, title, headings, body] = fields.as_array()?.as_slice() else {
                    return None;
                };
                let fields = [
                    (description.as_str()?, 4),
                    (title.as_str()?, 3),
                    (headings.as_str()?, 2),
                    (body.as_str()?, 1),
                ];
                let mut score = boost.as_i64()?;
                for (terms, weight) in &groups {
                    for term in terms {
                        for (field, points) in fields {
                            if field.contains(*term) {
                                score = score.checked_add(weight.checked_mul(points)?)?;
                            }
                        }
                    }
                }
                Some(score)
            })
            .collect()
    }
}

fn terms<'a>(payload: &'a Value, key: &str) -> Option<(Vec<&'a str>, i64)> {
    let [words, weight] = payload.get(key)?.as_array()?.as_slice() else {
        return None;
    };
    let words = words
        .as_array()?
        .iter()
        .map(Value::as_str)
        .collect::<Option<_>>()?;
    Some((words, weight.as_i64()?))
}
