//! owner: visibility and Kotlin extension-family facts for structural review.
//! allowed imports: JSON and ordered or keyed collections.
//! forbidden imports: filesystem, Git execution and approval policy.
//! callers/tests: structural owner diagnostics and native/Python parity fixtures.
//! verification: subset-specific grouping, stable labels and prior facts.
use serde_json::{json, Value};
use std::collections::{BTreeSet, HashMap};

pub(super) struct StructureOwnerFacts;

struct Declaration<'a> {
    name: &'a str,
    line: u64,
    receiver: Option<&'a str>,
    role: Option<&'a str>,
    public: bool,
}

impl StructureOwnerFacts {
    pub(super) fn measure(input: &Value) -> Option<Value> {
        let kotlin = input.get("group_extensions")?.as_bool()?;
        let default_export = input.get("default_export")?.as_bool()?;
        let current = Self::visible(input.get("declarations")?, kotlin, default_export)?;
        let previous = Self::visible(input.get("previous_declarations")?, kotlin, default_export)?;
        let public = Self::labels(current.iter().filter(|row| row.public));
        let visible = Self::labels(current.iter());
        Some(json!({
            "path": input.get("path")?.as_str()?,
            "public_count": public.len(),
            "previous_public_count": Self::labels(previous.iter().filter(|row| row.public)).len(),
            "public_labels": public.join(", "),
            "visible_count": visible.len(),
            "previous_visible_count": Self::labels(previous.iter()).len(),
            "visible_labels": visible[..visible.len().min(8)].join(", "),
            "roles": Self::roles(&current),
            "previous_roles": Self::roles(&previous),
            "role_labels": current.iter()
                .map(|row| format!("{}@{}", row.name, row.line)).collect::<Vec<_>>().join(", "),
        }))
    }

    fn visible(input: &Value, kotlin: bool, default_export: bool) -> Option<Vec<Declaration<'_>>> {
        let mut visible = Vec::new();
        for row in input.as_array()? {
            if row.get("private")?.as_bool()? {
                continue;
            }
            let receiver = Self::optional_text(row, "receiver")?;
            let role = Self::optional_text(row, "role")?;
            let grouped = kotlin && row.get("kind")?.as_str()? == "fun";
            visible.push(Declaration {
                name: row.get("name")?.as_str()?,
                line: row.get("line")?.as_u64()?,
                receiver: if grouped { receiver } else { None },
                role,
                public: !row.get("internal")?.as_bool()?
                    && (row.get("exported")?.as_bool()? || default_export),
            });
        }
        Some(visible)
    }

    fn optional_text<'a>(row: &'a Value, key: &str) -> Option<Option<&'a str>> {
        let value = row.get(key)?;
        if value.is_null() {
            Some(None)
        } else {
            let text = value.as_str()?;
            Some((!text.is_empty()).then_some(text))
        }
    }

    fn labels<'a>(rows: impl Iterator<Item = &'a Declaration<'a>> + Clone) -> Vec<String> {
        let mut family_sizes = HashMap::new();
        for receiver in rows.clone().filter_map(|row| row.receiver) {
            *family_sizes.entry(receiver).or_insert(0) += 1;
        }
        rows.filter_map(|row| match row.receiver {
            Some(receiver) => family_sizes
                .remove(receiver)
                .map(|size| format!("{receiver} extension family[{size}]@{}", row.line)),
            None => Some(format!("{}@{}", row.name, row.line)),
        })
        .collect()
    }

    fn roles<'a>(rows: &[Declaration<'a>]) -> BTreeSet<&'a str> {
        rows.iter().filter_map(|row| row.role).collect()
    }
}
