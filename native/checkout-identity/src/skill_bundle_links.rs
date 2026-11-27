//! Owner: scan the flat guidance card's Markdown link syntax in source order.
//! Allowed imports: JSON, paths, and the skill-bundle target resolver.
//! Forbidden imports: file writes, Markdown normalization, and provider clients.
//! Callers/tests: completion probe and skill bundle migration fixtures.
use super::skill_bundle_target;
use serde_json::{json, Value};
use std::path::Path;

pub(super) fn payload(input: &Value) -> Option<Value> {
    let root = Path::new(input.get("root")?.as_str()?);
    let old_path = Path::new(input.get("old_path")?.as_str()?);
    let new_path = Path::new(input.get("new_path")?.as_str()?);
    if !root.is_absolute() || !old_path.is_absolute() || !new_path.is_absolute() {
        return None;
    }
    let old_parent = old_path.parent()?;
    let new_parent = new_path.parent()?;
    let text = input.get("text")?.as_str()?;
    let mut output = String::with_capacity(text.len());
    let mut copied = 0;
    let mut cursor = 0;
    while let Some(offset) = text[cursor..].find('[') {
        let label = cursor + offset + 1;
        let Some(length) = text[label..].find(']') else {
            break;
        };
        // All opening brackets inside this label share the same first ']'.
        // Python's negated character classes also accept newlines.
        cursor = label + length + 1;
        if length == 0 || !text[cursor..].starts_with('(') {
            continue;
        }
        let target = cursor + 1;
        let Some(length) = text[target..].find(')') else {
            break;
        };
        let end = target + length;
        cursor = end + 1;
        if length == 0 {
            continue;
        }
        let replacement =
            skill_bundle_target::rewrite(root, old_parent, new_parent, &text[target..end])?;
        output.push_str(&text[copied..target]);
        output.push_str(&replacement);
        copied = end;
        if output.len() > 1024 * 1024 {
            return None;
        }
    }
    output.push_str(&text[copied..]);
    Some(json!({"text": output}))
}
