//! Shared ordered Figma text style fields for candidate counts and override runs.
use super::number::round_number;
use crate::python_json::{Object, Value};

pub(super) fn project(base: &Object, overrides: Option<&Object>) -> Option<Object> {
    let mut style = Object::new();
    for (field, rounded) in [
        ("fontFamily", false),
        ("fontPostScriptName", false),
        ("fontWeight", false),
        ("fontSize", true),
        ("italic", false),
        ("lineHeightPx", true),
        ("lineHeightPercent", true),
        ("lineHeightPercentFontSize", true),
        ("lineHeightUnit", false),
        ("letterSpacing", true),
        ("letterSpacingUnit", false),
        ("paragraphSpacing", true),
        ("textCase", false),
        ("textAlignHorizontal", false),
        ("textAlignVertical", false),
        ("textAutoResize", false),
        ("textDecoration", false),
        ("textTruncation", false),
        ("maxLines", false),
    ] {
        let value = overrides
            .and_then(|fields| fields.get(field))
            .or_else(|| base.get(field))
            .unwrap_or(&Value::Null);
        let projected = if rounded {
            match value {
                Value::Number(value) => Value::Number(round_number(value)?),
                _ => Value::Null,
            }
        } else {
            value.clone()
        };
        style.insert(field.into(), projected);
    }
    Some(style)
}
