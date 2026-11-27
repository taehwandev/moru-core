//! owner: offline Figma validation CLI ingress; allowed imports: source guard,
//! pure JSON/validation/report owners and std file I/O; forbidden: network,
//! token access, Figma extraction, writes to input; callers/tests: launcher_main,
//! test_native_figma_validate; verification: reference parity and no-Python tests.
use crate::{
    figma_coverage::FigmaCoverage,
    figma_validation::FigmaValidation,
    figma_validation_report::FigmaReport,
    pretool_guard::CallbackGuard,
    python_input_file::{FileRead, PythonInputFile},
    python_json::PythonJson,
    python_text::PythonUtf8,
    text::Text,
};
use std::{ffi::OsString, io::Write};

mod direct_profile {
    include!(concat!(env!("OUT_DIR"), "/figma_direct_profile.rs"));
}

struct Outcome {
    code: i32,
    stdout: String,
    stderr: String,
}

pub(crate) struct FigmaProcess;
impl FigmaProcess {
    pub(crate) fn probe(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let fields = request.as_object()?;
        let path = fields.get("path")?.as_str()?;
        if fields.len() != 3
            || fields.get("python_profile")?.as_str()? != direct_profile::PYTHON_PROFILE
            || fields.get("source_root")?.as_str()? != root.to_str()?
            || !crate::python_encoding::PythonEncoding::utf8()
            || !std::path::Path::new(path).is_file()
        {
            return None;
        }
        // evaluate rechecks the opened inode and declines device/descriptor
        // aliases before reading. A declined probe must leave streams untouched.
        let result = Self::evaluate(&OsString::from(path))?;
        let receipt = serde_json::json!({
            "code": result.code, "stdout": result.stdout, "stderr": result.stderr,
        });
        (serde_json::to_vec(&receipt).ok()?.len() <= 1024 * 1024 - 64).then_some(receipt)
    }

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
        let bytes = match PythonInputFile::read(path, 64 * 1024 * 1024, false)? {
            FileRead::Bytes(bytes) => bytes,
            FileRead::Error(error) => return Some(Self::read_error(error)),
            FileRead::TooLarge => return None,
        };
        let text = match PythonUtf8::decode(&bytes) {
            Ok(text) => Text::universal_newlines(text),
            Err(error) => return Some(Self::read_error(error)),
        };
        let summary = match PythonJson::parse(&text) {
            Some(summary) => summary,
            None => return Some(Self::read_error(PythonJson::error(&text)?)),
        };
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

    fn read_error(error: String) -> Outcome {
        Outcome {
            code: 2,
            stdout: String::new(),
            stderr: format!("ERROR: cannot read summary: {error}\n"),
        }
    }
}
