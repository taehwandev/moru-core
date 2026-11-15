//! Owner: UnittestAdmission, the pre-interpreter release latch and same-PID exec.
//! Allowed imports: std I/O, paths and Unix process exec. Forbidden: project
//! imports, discovery, receipts, authorization, child spawning or Python fallback.
//! Caller: verified native bootstrap in agent_verification_hook; verification:
//! unittest_admission_tests and tests/test_native_unittest_admission.py.
use std::{
    ffi::OsString,
    io::{self, Read},
    os::unix::process::CommandExt,
    path::Path,
    process::Command,
};

pub(crate) struct UnittestAdmission;

impl UnittestAdmission {
    pub(crate) fn run(args: &[OsString]) -> i32 {
        let Some(program) = args
            .first()
            .filter(|program| Path::new(program).is_absolute())
        else {
            eprintln!("moru-native-launcher: unittest admission requires an absolute executable");
            return 2;
        };
        if !released(io::stdin().lock()) {
            return 125;
        }
        let error = Command::new(program)
            .args(&args[1..])
            .env_remove("MORU_UNITTEST_ADMISSION")
            .exec();
        eprintln!("moru-native-launcher: admitted unittest exec failed: {error}");
        127
    }
}

fn released(mut input: impl Read) -> bool {
    let mut byte = [0];
    input.read_exact(&mut byte).is_ok() && byte == [1]
}

#[cfg(test)]
#[path = "unittest_admission_tests.rs"]
mod tests;
