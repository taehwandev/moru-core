//! owner: structural owner budget and role diagnostics from prepared declarations.
//! allowed imports: JSON and formatting.
//! forbidden imports: source reads, Git execution, writes and approval.
//! callers/tests: structural diagnostic batch and prepared declaration parity.
//! verification: baseline budgets, blocked role expansion and exact order.
use super::structure_owner_facts::StructureOwnerFacts;
use serde_json::{json, Value};

pub(super) struct StructureOwnerFindings;

impl StructureOwnerFindings {
    pub(super) fn inspect(input: &Value) -> Option<Value> {
        let rows = input.get("files")?.as_array()?;
        let public_limit = input.get("public_limit")?.as_u64()?;
        let visible_limit = input.get("visible_limit")?.as_u64()?;
        let role_pairs = input
            .get("role_pairs")?
            .as_array()?
            .iter()
            .map(|pair| Some((pair.get(0)?.as_str()?, pair.get(1)?.as_str()?)))
            .collect::<Option<Vec<_>>>()?;
        let mut findings = Vec::new();
        for row in rows {
            let measured;
            let row = if row.get("declarations").is_some() {
                measured = StructureOwnerFacts::measure(row)?;
                &measured
            } else {
                row
            };
            let path = row.get("path")?.as_str()?;
            let public = row.get("public_count")?.as_u64()?;
            let visible = row.get("visible_count")?.as_u64()?;
            if public > public_limit && public > row.get("previous_public_count")?.as_u64()? {
                let shown = row.get("public_labels")?.as_str()?;
                findings.push(format!(
                    "{path} declares {public} public/exported top-level owners ({shown}); \
                     limit is {public_limit}; split runtime files so one file owns one \
                     public contract, component, handler, service, or implementation; \
                     for a legacy multi-owner file, keep existing exports and place the new helper \
                     in a purpose-named module"
                ));
            }
            if visible > visible_limit && visible > row.get("previous_visible_count")?.as_u64()? {
                let shown = row.get("visible_labels")?.as_str()?;
                findings.push(format!(
                    "{path} declares {visible} non-private top-level owners ({shown}); \
                     limit is {visible_limit}; move separate contracts, state, data, platform, and helpers \
                     into purpose-named files"
                ));
            }
            let roles = Self::roles(row, "roles")?;
            let previous = Self::roles(row, "previous_roles")?;
            let blocked = |set: &[&str]| {
                role_pairs
                    .iter()
                    .any(|(left, right)| set.contains(left) && set.contains(right))
            };
            if blocked(&roles)
                && (!blocked(&previous) || roles.iter().any(|role| !previous.contains(role)))
            {
                let shown = row.get("role_labels")?.as_str()?;
                let roles = roles.join(", ");
                findings.push(format!(
                    "{path} mixes top-level owner roles {roles} ({shown}); split by purpose before approval"
                ));
            }
        }
        Some(json!(findings))
    }

    fn roles<'a>(row: &'a Value, name: &str) -> Option<Vec<&'a str>> {
        row.get(name)?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect()
    }
}
