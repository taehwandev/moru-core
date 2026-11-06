//! owner: offline Figma validation CLI ingress; allowed imports: source guard,
//! pure JSON/validation/report owners and std file I/O; forbidden: network,
//! token access, Figma extraction, writes to input; callers/tests: launcher_main,
//! test_native_figma_validate; verification: reference parity and no-Python tests.
use crate::{
    figma_coverage::FigmaCoverage, figma_validation::FigmaValidation,
    figma_validation_report::FigmaReport, pretool_guard::CallbackGuard, python_json::PythonJson,
};
use std::{
    ffi::OsString,
    fs,
    io::{Read, Write},
    os::unix::fs::OpenOptionsExt,
};

pub(crate) struct FigmaProcess;
impl FigmaProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(_) = CallbackGuard::root(launcher, "git") else {
            crate::exec_python(launcher, args);
        };
        if args.len() != 2 {
            return if std::io::stderr()
                .write_all(b"usage: python3 figma_validate.py <design-summary.json>\n")
                .is_ok()
            {
                2
            } else {
                1
            };
        }
        if !crate::python_encoding::PythonEncoding::utf8() {
            crate::exec_python(launcher, args);
        }
        let Some((code, output)) = Self::evaluate(&args[1]) else {
            crate::exec_python(launcher, args);
        };
        if std::io::stdout().write_all(output.as_bytes()).is_err() {
            1
        } else {
            code
        }
    }

    fn evaluate(path: &OsString) -> Option<(i32, String)> {
        // Do not consume streams/devices before a potential Python fallback.
        // Bounded regular-file reads also leave malformed JSON diagnostics to
        // the reference until the shared parser owns exact Python error text.
        const LIMIT: u64 = 64 * 1024 * 1024;
        let canonical = fs::canonicalize(path).ok()?;
        // Descriptor namespaces can share an existing stream position on Darwin.
        // Defer before opening so Python owns that read exactly once.
        if canonical.starts_with("/dev") || canonical.starts_with("/proc") {
            return None;
        }
        let metadata = fs::metadata(&canonical).ok()?;
        if !metadata.is_file() || metadata.len() > LIMIT {
            return None;
        }
        // A concurrent leaf replacement must not block on a FIFO before fstat.
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_NOFOLLOW)
            .open(&canonical)
            .ok()?;
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut bytes = Vec::new();
        file.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > LIMIT {
            return None;
        }
        let text = std::str::from_utf8(&bytes).ok()?;
        let summary = PythonJson::parse(text)?;
        let problems = FigmaValidation::validate(&summary)?;
        let coverage = FigmaCoverage::compute(&summary)?;
        let mut output = FigmaReport::render(&coverage, &problems)?;
        // Python print(format_report(...)) adds a second final newline.
        output.push('\n');
        Some((if problems.is_empty() { 0 } else { 1 }, output))
    }
}
