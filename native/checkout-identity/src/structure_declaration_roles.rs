//! owner: ordered name-based role classification for structural review.
//! allowed imports: ASCII text operations and JSON.
//! forbidden imports: filesystem, Git execution and approval decisions.
//! callers/tests: declaration materialization through the private completion probe.
//! verification: Python role parity, priority, and non-ASCII fallback.
use serde_json::{json, Value};

pub(super) struct StructureDeclarationRoles;

impl StructureDeclarationRoles {
    pub(super) fn classify(input: &Value) -> Option<Value> {
        let rules = input
            .get("rules")?
            .as_array()?
            .iter()
            .map(|rule| Some((rule.get(0)?.as_str()?, Self::patterns(rule.get(1)?)?)))
            .collect::<Option<Vec<_>>>()?;
        let excluded = Self::patterns(input.get("function_excluded")?)?;
        let mut roles = Vec::new();
        for entry in input.get("declarations")?.as_array()? {
            let kind = entry.get(0)?.as_str()?;
            let name = entry.get(1)?.as_str()?;
            if !name.is_ascii() {
                roles.push(Value::Bool(false));
                continue;
            }
            let skip = if matches!(kind, "fn" | "fun" | "func" | "function") {
                excluded.as_slice()
            } else {
                &[]
            };
            let (normalized, tokens) = Self::name_parts(name);
            let role = rules.iter().find_map(|(role, patterns)| {
                patterns
                    .iter()
                    .any(|&pattern| {
                        !skip.contains(&pattern)
                            && (tokens.iter().any(|token| token == pattern)
                                || (pattern.len() > 4 && normalized.contains(pattern)))
                    })
                    .then_some(*role)
            });
            roles.push(json!(role));
        }
        Some(json!({"roles": roles}))
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
