//! owner: InputDiagnostic; allowed imports: std strings; forbidden imports: I/O,
//! subprocesses and runtime state; callers/tests: ManifestParser and behavior
//! evaluator CLI; verification: caller digit policy and path-prefix parity.

#[derive(Debug)]
pub(crate) enum InputDiagnostic {
    Syntax(String),
    IntegerLimit {
        limit: usize,
        digits: usize,
        builder_text: Option<String>,
    },
}
