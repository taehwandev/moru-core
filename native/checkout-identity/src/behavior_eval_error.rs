//! owner: BehaviorEvalError; allowed imports: std strings; forbidden imports:
//! filesystem, process and provider access; callers/tests: offline grader schema
//! and CLI; verification: public diagnostic and Python fallback parity.

pub(crate) enum BehaviorEvalError {
    Stable(String),
    Reference(String),
}

impl From<&'static str> for BehaviorEvalError {
    fn from(detail: &'static str) -> Self {
        Self::Stable(detail.to_owned())
    }
}

impl From<String> for BehaviorEvalError {
    fn from(detail: String) -> Self {
        Self::Reference(detail)
    }
}
