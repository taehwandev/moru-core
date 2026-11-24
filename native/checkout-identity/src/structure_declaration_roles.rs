//! owner: ordered name-based role classification and package boundary role notes.
//! allowed imports: ASCII text operations and JSON.
//! forbidden imports: filesystem, Git execution and approval decisions.
//! callers/tests: declaration materialization through the private completion probe.
//! verification: Python role parity, priority, and non-ASCII fallback.
use serde_json::{json, Value};
use std::collections::BTreeSet;

type RoleRule<'a> = (&'a str, Vec<&'a str>);

pub(super) struct StructureDeclarationRoles;

impl StructureDeclarationRoles {
    pub(super) fn classify(input: &Value) -> Option<Value> {
        let declarations = input
            .get("declarations")?
            .as_array()?
            .iter()
            .map(|entry| Some((entry.get(0)?.as_str()?, entry.get(1)?.as_str()?)))
            .collect::<Option<Vec<_>>>()?;
        Some(json!({"roles": Self::classify_names(input, declarations)?}))
    }

    pub(super) fn classify_names<'a>(
        input: &Value,
        declarations: impl IntoIterator<Item = (&'a str, &'a str)>,
    ) -> Option<Vec<Value>> {
        let rules = Self::rules(input)?;
        let excluded = Self::patterns(input.get("function_excluded")?)?;
        let mut roles = Vec::new();
        for (kind, name) in declarations {
            if !name.is_ascii() {
                roles.push(Value::Bool(false));
                continue;
            }
            let skip = if matches!(kind, "fn" | "fun" | "func" | "function") {
                excluded.as_slice()
            } else {
                &[]
            };
            roles.push(json!(Self::role(name, &rules, skip)));
        }
        Some(roles)
    }

    pub(super) fn boundary_reasons(input: &Value) -> Option<Value> {
        let rules = Self::rules(input)?;
        let mut reasons = Vec::new();
        if input.get("missing_in_head")?.as_bool()? {
            reasons.push("new runtime package/folder".to_owned());
        }
        for (field, label) in [
            ("added", "new files introduce multiple roles"),
            ("siblings", "package now contains multiple roles"),
        ] {
            let mut roles = BTreeSet::new();
            for entry in input.get(field)?.as_array()? {
                let name = entry.as_str()?;
                if !name.is_ascii() {
                    return None;
                }
                roles.extend(Self::role(name, &rules, &[]));
            }
            if roles.len() > 1 {
                reasons.push(format!(
                    "{label}: {}",
                    roles.into_iter().collect::<Vec<_>>().join(", ")
                ));
            }
        }
        Some(json!({"reasons": reasons}))
    }

    fn rules(input: &Value) -> Option<Vec<RoleRule<'_>>> {
        input
            .get("rules")?
            .as_array()?
            .iter()
            .map(|rule| Some((rule.get(0)?.as_str()?, Self::patterns(rule.get(1)?)?)))
            .collect()
    }

    fn role<'a>(name: &str, rules: &[RoleRule<'a>], skip: &[&str]) -> Option<&'a str> {
        let (normalized, tokens) = Self::name_parts(name);
        rules.iter().find_map(|(role, patterns)| {
            patterns
                .iter()
                .any(|&pattern| {
                    !skip.contains(&pattern)
                        && (tokens.iter().any(|token| token == pattern)
                            || (pattern.len() > 4 && normalized.contains(pattern)))
                })
                .then_some(*role)
        })
    }

    fn patterns(value: &Value) -> Option<Vec<&str>> {
        value
            .as_array()?
            .iter()
            .map(|item| item.as_str().filter(|text| text.is_ascii()))
            .collect()
    }

    fn name_parts(name: &str) -> (String, Vec<String>) {
        let mut normalized = String::with_capacity(name.len());
        let mut token = String::new();
        let mut tokens = Vec::new();
        let mut previous_lower_or_digit = false;
        for byte in name.bytes() {
            let alnum = byte.is_ascii_alphanumeric();
            if (!alnum || (previous_lower_or_digit && byte.is_ascii_uppercase()))
                && !token.is_empty()
            {
                tokens.push(std::mem::take(&mut token));
            }
            if alnum {
                let lower = char::from(byte.to_ascii_lowercase());
                normalized.push(lower);
                token.push(lower);
            }
            previous_lower_or_digit = byte.is_ascii_lowercase() || byte.is_ascii_digit();
        }
        if !token.is_empty() {
            tokens.push(token);
        }
        (normalized, tokens)
    }
}
