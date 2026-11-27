//! Shared route-token grammar for trend source projection and metadata.
use crate::text::Text;

pub(super) fn route_token(raw: &str) -> Option<&str> {
    let token = Text::py_strip(raw);
    let mut bytes = token.bytes();
    ((2..=33).contains(&token.len())
        && bytes.next().is_some_and(|byte| byte.is_ascii_lowercase())
        && bytes.all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
        }))
    .then_some(token)
}
