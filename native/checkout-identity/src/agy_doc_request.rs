//! owner: AGY required-document request decoding;
//! allowed imports: JSON; forbidden imports: filesystem, session authority,
//! delivery state and providers; callers/tests: native document delivery probe,
//! standalone hook and AGY adapter fixtures; verification: bounded request parity.
use serde_json::{json, Map, Value};

pub(super) fn decode(args: &Map<String, Value>) -> Option<Value> {
    if args.len() != 1 {
        return None;
    }
    if let Some(raw) = args.get("raw") {
        let raw = raw.as_str()?;
        if raw.len() > 128 * 1024 {
            return None;
        }
        if raw.is_empty() {
            return Some(json!(["", [], ""]));
        }
        let payload: Value = serde_json::from_str(raw).ok()?;
        return project(&payload);
    }
    project(args.get("payload")?)
}

fn project(payload: &Value) -> Option<Value> {
    let Some(payload) = payload.as_object() else {
        return Some(json!(["", [], ""]));
    };
    let strings = |key| match payload.get(key) {
        None | Some(Value::Null) => Some(""),
        Some(Value::String(text)) => Some(text.as_str()),
        _ => None,
    };
    let conversation = strings("conversationId")?;
    let workspaces = match payload.get("workspacePaths") {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(items)) => items.iter().map(Value::as_str).collect::<Option<_>>()?,
        _ => return None,
    };
    let transcript = if conversation.is_empty() || workspaces.is_empty() {
        ""
    } else {
        strings("transcriptPath")?
    };
    Some(json!([conversation, workspaces, transcript]))
}
