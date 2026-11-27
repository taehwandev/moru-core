//! owner: ordinary Figma URL target resolution; allowed imports: JSON and text;
//! forbidden imports: filesystem, environment and network; callers/tests: Figma
//! process probe and extractor target fixtures; verification: target/error parity.
use crate::text::Text;
use serde_json::{json, Value};

fn decode(text: &str, query: bool) -> Option<String> {
    let mut source = text.as_bytes().iter().copied();
    let mut bytes = Vec::with_capacity(text.len());
    while let Some(byte) = source.next() {
        bytes.push(match byte {
            b'%' => {
                let hi = char::from(source.next()?).to_digit(16)?;
                let lo = char::from(source.next()?).to_digit(16)?;
                (hi * 16 + lo) as u8
            }
            b'+' if query => b' ',
            other => other,
        });
    }
    String::from_utf8(bytes).ok()
}

fn url_fields(url: &str, key: &mut String, node: &mut String) -> Option<()> {
    if url.bytes().any(|b| b <= b' ' || b == 127) {
        return None;
    }
    let url = url.strip_prefix("https://")?.split('#').next()?;
    let (base, query) = url.split_once('?').unwrap_or((url, ""));
    let (host, path) = base.split_once('/').unwrap_or((base, ""));
    if !matches!(host, "figma.com" | "www.figma.com") || path.contains(';') {
        return None;
    }
    let mut parts = path.split('/').filter(|part| !part.is_empty());
    while let Some(part) = parts.next() {
        if matches!(decode(part, false)?.as_str(), "file" | "design" | "proto") {
            if let Some(next) = parts.next() {
                *key = decode(next, false)?;
            }
            break;
        }
    }

    let mut hyphen = None;
    let mut underscore = None;
    for field in query.split('&') {
        let Some((name, value)) = field.split_once('=') else {
            continue;
        };
        if value.is_empty() {
            continue;
        }
        let slot = match decode(name, true)?.as_str() {
            "node-id" => &mut hyphen,
            "node_id" => &mut underscore,
            _ => continue,
        };
        if slot.is_none() {
            *slot = Some(decode(value, true)?);
        }
    }
    if let Some(value) = hyphen.or(underscore) {
        *node = value;
    }
    Some(())
}

pub(super) struct Target;
impl Target {
    pub(super) fn normalize(node: &str) -> Option<String> {
        let decoded = decode(node, false)?;
        if !decoded.is_ascii() {
            return None;
        }
        let mut nodes = Vec::new();
        for part in Text::py_strip(&decoded).split(';') {
            let body = part.strip_prefix('I').unwrap_or(part);
            let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
            if body
                .split_once('-')
                .is_some_and(|(a, b)| digits(a) && digits(b))
            {
                nodes.push(part.replace('-', ":"));
            } else {
                nodes.push(part.to_owned());
            }
        }
        Some(nodes.join(";"))
    }

    pub(super) fn resolve(text: &str) -> Option<Value> {
        if text.len() > 1024 * 1024 {
            return None;
        }
        let input: Value = serde_json::from_str(text).ok()?;
        let field = |name: &str| match input.get(name)? {
            Value::Null => Some(""),
            other => other.as_str(),
        };
        let mut key = field("file_key")?.to_owned();
        let mut node = field("node_id")?.to_owned();
        let url = field("url")?;
        if !url.is_empty() {
            url_fields(url, &mut key, &mut node)?;
        }
        if key.is_empty() {
            return Some(json!({"error":"Missing Figma file key. Pass --url or --file-key."}));
        }
        if node.is_empty() {
            return Some(
                json!({"error":"Missing Figma node id. Pass a frame URL with node-id or --node-id."}),
            );
        }
        Some(json!({"file_key":key,"node_id":Self::normalize(&node)?}))
    }
}
