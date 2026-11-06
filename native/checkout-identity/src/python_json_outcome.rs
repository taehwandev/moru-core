//! owner: ParseOutcome; allowed imports: PythonJson Value; forbidden imports: process/network;
//! callers/tests: shared parser, statusline; verification: error classification tests.
use super::Value;
#[derive(Debug)]
pub(crate) enum ParseOutcome {
    Value(Value),
    Invalid,
    Unsupported,
}
