//! owner: threshold projection of structural net-deletion findings.
//! allowed imports: JSON and standard-library arithmetic.
//! forbidden imports: filesystem, Git, sample output and review decisions.
//! callers/tests: batched structure source selection and parity fixtures.
//! verification: inclusive threshold, path ordering and overflow fallback.
use serde_json::{json, Value};

pub(super) struct StructureNetDeletions;

impl StructureNetDeletions {
    pub(super) fn findings(input: &Value) -> Option<Value> {
        let limit = input.get("limit")?.as_i64()?;
        let rows = input.get("counts")?.as_array()?;
        let mut findings = Vec::new();
        for row in rows {
            let path = row.get(0)?.as_str()?;
            let additions = row.get(1)?.as_i64()?;
            let deletions = row.get(2)?.as_i64()?;
            let net = deletions.checked_sub(additions)?;
            if net >= limit {
                findings.push((path, additions, deletions, net));
            }
        }
        findings.sort_by(|left, right| left.0.cmp(right.0));
        Some(json!(findings
            .into_iter()
            .map(|(path, additions, deletions, net)| {
                json!({"path": path, "additions": additions, "deletions": deletions, "net": net})
            })
            .collect::<Vec<_>>()))
    }
}
