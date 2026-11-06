//! owner: JsonDiagnostic; allowed imports: std and generated decoder contract;
//! forbidden imports: parsing/I/O; callers/tests: ManifestParser; verification: error positions.
include!(concat!(env!("OUT_DIR"), "/json_contract.rs"));
pub(super) struct JsonDiagnostic;
impl JsonDiagnostic {
    pub(super) fn syntax(text: &str, offset: usize, message: &str) -> String {
        let prefix = &text[..offset];
        let position = prefix.chars().count();
        let line = prefix.bytes().filter(|b| *b == b'\n').count() + 1;
        let column = prefix
            .rsplit_once('\n')
            .map_or(prefix, |(_, tail)| tail)
            .chars()
            .count()
            + 1;
        format!("{message}: line {line} column {column} (char {position})")
    }
    pub(super) fn trailing(array: bool) -> bool {
        if array {
            JSON_ARRAY_TRAILING
        } else {
            JSON_OBJECT_TRAILING
        }
    }
    pub(super) fn digits(limit: usize, digits: usize) -> Option<String> {
        Some(
            JSON_DIGIT_ERROR?
                .replace("{limit}", &limit.to_string())
                .replace("{digits}", &digits.to_string()),
        )
    }
}
