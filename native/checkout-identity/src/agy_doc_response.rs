//! owner: standalone AGY document hook stdout encoding;
//! allowed imports: Python-compatible JSON text encoding;
//! forbidden imports: filesystem, delivery state, providers and stdout writes;
//! callers/tests: private doc transcript probe and standalone hook parity;
//! verification: exact Python bytes, bounded input and no trailing newline.
use crate::python_text::PythonText;

pub(super) fn encode(text: &str) -> Option<String> {
    if text.len() > 128 * 1024 {
        return None;
    }
    if text.is_empty() {
        return Some("{}".into());
    }
    let encoded = PythonText::json_ascii(text)?;
    Some(format!(
        r#"{{"injectSteps": [{{"systemMessage": {{"systemMessage": {encoded}}}}}]}}"#
    ))
}
