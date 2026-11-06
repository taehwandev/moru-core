//! owner: offline Figma validation CLI ingress; allowed imports: source guard,
//! pure JSON/validation/report owners and std file I/O; forbidden: network,
//! token access, Figma extraction, writes to input; callers/tests: launcher_main,
//! test_native_figma_validate; verification: reference parity and no-Python tests.
use crate::{
    figma_coverage::FigmaCoverage, figma_validation::FigmaValidation,
    figma_validation_report::FigmaReport, pretool_guard::CallbackGuard, python_json::PythonJson,
};
#[path = "figma_file.rs"]
mod file;
use std::{ffi::OsString, io::Write};

struct Outcome {
    code: i32,
    stdout: String,
    stderr: String,
}

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
        let Some(output) = Self::evaluate(&args[1]) else {
            crate::exec_python(launcher, args);
        };
        if std::io::stdout()
            .write_all(output.stdout.as_bytes())
            .is_err()
            || std::io::stderr()
                .write_all(output.stderr.as_bytes())
                .is_err()
        {
            1
        } else {
            output.code
        }
    }

    fn evaluate(path: &OsString) -> Option<Outcome> {
        let bytes = match file::FigmaFile::read(path)? {
            file::FileRead::Bytes(bytes) => bytes,
            file::FileRead::Error(stderr) => {
                return Some(Outcome {
                    code: 2,
                    stdout: String::new(),
                    stderr,
                })
            }
        };
        let text = std::str::from_utf8(&bytes).ok()?;
        let summary = PythonJson::parse(text)?;
        let problems = FigmaValidation::validate(&summary)?;
        let coverage = FigmaCoverage::compute(&summary)?;
        let mut output = FigmaReport::render(&coverage, &problems)?;
        // Python print(format_report(...)) adds a second final newline.
        output.push('\n');
        Some(Outcome {
            code: if problems.is_empty() { 0 } else { 1 },
            stdout: output,
            stderr: String::new(),
        })
    }
}
