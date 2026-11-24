//! owner: visibility and declaration-family facts for structural review.
//! allowed imports: Python-compatible text, JSON and ordered or keyed collections.
//! forbidden imports: filesystem, Git execution and approval policy.
//! callers/tests: structural owner diagnostics and native/Python parity fixtures.
//! verification: subset-specific grouping, stable labels and prior facts.
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};
use std::collections::{BTreeSet, HashMap, HashSet};

pub(super) struct StructureOwnerFacts;

struct Declaration<'a> {
    name: &'a str,
    line: u64,
    receiver: Option<&'a str>,
    role: Option<&'a str>,
    source: &'a str,
    public: bool,
}

impl StructureOwnerFacts {
    pub(super) fn measure(input: &Value) -> Option<Value> {
        let kotlin = input.get("group_extensions")?.as_bool()?;
        let dart = input.get("group_sealed")?.as_bool()?;
        let default_export = input.get("default_export")?.as_bool()?;
        let current = Self::visible(input.get("declarations")?, kotlin, dart, default_export)?;
        let previous = Self::visible(
            input.get("previous_declarations")?,
            kotlin,
            dart,
            default_export,
        )?;
        if dart
            && !PythonText::matches_unicode_version(input.get("unicode")?.as_str()?)
            && current
                .iter()
                .chain(&previous)
                .any(|row| !row.source.is_ascii())
        {
            return None;
        }
        let public = Self::labels(current.iter().filter(|row| row.public), dart);
        let visible = Self::labels(current.iter(), dart);
        Some(json!({
            "path": input.get("path")?.as_str()?,
            "public_count": public.len(),
            "previous_public_count": Self::labels(previous.iter().filter(|row| row.public), dart).len(),
            "public_labels": public.join(", "),
            "visible_count": visible.len(),
            "previous_visible_count": Self::labels(previous.iter(), dart).len(),
            "visible_labels": visible[..visible.len().min(8)].join(", "),
            "roles": Self::roles(&current),
            "previous_roles": Self::roles(&previous),
            "role_labels": current.iter()
                .map(|row| format!("{}@{}", row.name, row.line)).collect::<Vec<_>>().join(", "),
        }))
    }

    fn visible(
        input: &Value,
        kotlin: bool,
        dart: bool,
        default_export: bool,
    ) -> Option<Vec<Declaration<'_>>> {
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
                source: if dart {
                    row.get("source")?.as_str()?
                } else {
                    ""
                },
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

    fn labels<'a>(
        rows: impl Iterator<Item = &'a Declaration<'a>> + Clone,
        dart: bool,
    ) -> Vec<String> {
        if dart {
            return Self::sealed_labels(rows);
        }
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

    fn sealed_labels<'a>(rows: impl Iterator<Item = &'a Declaration<'a>> + Clone) -> Vec<String> {
        let sealed: HashSet<_> = rows
            .clone()
            .filter_map(|row| Self::sealed_name(row.source))
            .collect();
        rows.filter_map(|row| {
            if sealed.contains(row.name) {
                Some(format!("{} sealed family@{}", row.name, row.line))
            } else if !sealed.is_empty() && Self::inherits_sealed(row.source, &sealed) {
                None
            } else {
                Some(format!("{}@{}", row.name, row.line))
            }
        })
        .collect()
    }

    fn sealed_name(source: &str) -> Option<&str> {
        let source = Self::after_keyword(source, "abstract").unwrap_or(source);
        let name = Self::after_keyword(Self::after_keyword(source, "sealed")?, "class")?;
        if !name
            .as_bytes()
            .first()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || *byte == b'_')
        {
            return None;
        }
        Some(&name[..name.find(|ch| !PythonText::word(ch)).unwrap_or(name.len())])
    }

    fn after_keyword<'a>(source: &'a str, keyword: &str) -> Option<&'a str> {
        let tail = source.strip_prefix(keyword)?;
        tail.chars().next().filter(|&ch| Text::is_py_space(ch))?;
        Some(tail.trim_start_matches(Text::is_py_space))
    }

    fn inherits_sealed(source: &str, sealed: &HashSet<&str>) -> bool {
        let header = source.split('{').next().unwrap_or("");
        // Python's whole-word search allows any later token after an inheritance
        // keyword, but the regex dot cannot cross LF.
        header.split('\n').any(|line| {
            let mut words = line.split(|ch| !PythonText::word(ch));
            words
                .by_ref()
                .any(|word| matches!(word, "extends" | "implements"))
                && words.any(|word| sealed.contains(word))
        })
    }

    fn roles<'a>(rows: &[Declaration<'a>]) -> BTreeSet<&'a str> {
        rows.iter().filter_map(|row| row.role).collect()
    }
}
