//! owner: ReadProcess; allowed imports: std process/thread/io/time;
//! forbidden imports: shell construction, repository policy, writes;
//! callers/tests: GitRead, PsParent; verification: raw pipes and bounded deadlines.
use std::{process::Command, time::Duration};

#[path = "read_process_status.rs"]
pub(crate) mod status;

// None covers runner uncertainty; exit status and raw pipes stay separate so
// each caller can preserve its reference decoding and failure behavior.
pub(crate) fn capture_raw(
    command: &mut Command,
    timeout: Duration,
) -> Result<Option<(Vec<u8>, Vec<u8>, bool)>, ()> {
    status::capture_status(command, timeout, None, None)
        .map(|result| result.map(|(out, err, status)| (out, err, status.success())))
}

#[cfg(test)]
#[path = "read_process_tests.rs"]
mod tests;
