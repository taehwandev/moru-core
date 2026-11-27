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
    python_json::{Number, PythonJson, Value},
    python_text::PythonUtf8,
    text::Text,
};
use std::{
    ffi::OsString,
    io::{Read, Write},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
};

#[path = "figma_frames.rs"]
mod frames;
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
    fn bound_input<'a>(
        request: &'a serde_json::Value,
        root: &std::path::Path,
        key: &str,
    ) -> Option<&'a str> {
        let fields = request.as_object()?;
        if fields.len() != 3
            || fields.get("python_profile")?.as_str()? != direct_profile::PYTHON_PROFILE
            || fields.get("source_root")?.as_str()? != root.to_str()?
            || !crate::python_encoding::PythonEncoding::utf8()
        {
            return None;
        }
        fields.get(key)?.as_str()
    }

    fn receipt(value: serde_json::Value) -> Option<serde_json::Value> {
        (serde_json::to_vec(&value).ok()?.len() <= 1024 * 1024 - 64).then_some(value)
    }

    pub(crate) fn schema(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let text = Self::bound_input(request, root, "text")?;
        let summary = PythonJson::parse(text)?;
        Self::receipt(serde_json::json!({"problems": FigmaValidation::validate(&summary)?}))
    }

    pub(crate) fn frames(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let data = serde_json::from_str(Self::bound_input(request, root, "text")?).ok()?;
        Self::receipt(frames::analyze(&data, false)?)
    }

    pub(crate) fn smoke_analysis(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let summary = PythonJson::parse(Self::bound_input(request, root, "text")?)?;
        Self::smoke(&summary, None)
    }

    pub(crate) fn smoke_verdict(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let input = PythonJson::parse(Self::bound_input(request, root, "text")?)?;
        let Value::Bool(quick) = input.get("quick")? else {
            return None;
        };
        Self::smoke(input.get("summary")?, Some(*quick))
    }

    pub(crate) fn smoke_result(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let input = PythonJson::parse(Self::bound_input(request, root, "text")?)?;
        Self::bundle_result(&input, input.get("summary")?)
    }

    pub(crate) fn smoke_file_result(
        request: &serde_json::Value,
        root: &Path,
    ) -> Option<serde_json::Value> {
        let input = PythonJson::parse(Self::bound_input(request, root, "text")?)?;
        let path = Path::new(input.get("bundle_root")?.as_str()?);
        if path.parent().is_none()
            || PythonInputFile::through_descriptor(path)
            || path.canonicalize().ok()?.as_os_str() != path.as_os_str()
        {
            return None;
        }
        let directory =
            crate::atomic_sibling::AtomicSibling::open_directory(&path.join("summary"))?;
        let bytes = Self::summary_bytes(&directory)?;
        let text = Text::universal_newlines(PythonUtf8::decode(&bytes).ok()?);
        Self::bundle_result(&input, &PythonJson::parse(&text)?)
    }

    fn summary_bytes(directory: &std::fs::File) -> Option<Vec<u8>> {
        const LIMIT: u64 = 8 * 1024 * 1024;
        let name = c"design-summary.json";
        let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name.as_ptr(),
                stat.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } != 0
        {
            return None;
        }
        let stat = unsafe { stat.assume_init() };
        if stat.st_mode & libc::S_IFMT != libc::S_IFREG || stat.st_nlink != 1 {
            return None;
        }
        let file = crate::atomic_sibling::AtomicSibling::open_relative(
            directory,
            name,
            libc::O_RDONLY | libc::O_NOCTTY | libc::O_NONBLOCK,
        )?;
        let meta = file.metadata().ok()?;
        if !meta.is_file()
            || meta.nlink() != 1
            || meta.ino() != stat.st_ino as u64
            || meta.dev() != stat.st_dev as u64
            || meta.len() > LIMIT
        {
            return None;
        }
        let mut bytes = Vec::new();
        file.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        (bytes.len() as u64 == meta.len()).then_some(bytes)
    }

    fn bundle_result(input: &Value, summary: &Value) -> Option<serde_json::Value> {
        let Value::Bool(quick) = input.get("quick")? else {
            return None;
        };
        let Value::Number(scale) = input.get("scale")? else {
            return None;
        };
        let fields = summary.as_object()?;
        let screens: serde_json::Value = match fields.get("screens") {
            None => serde_json::json!([]),
            Some(screens) => {
                serde_json::from_str(&PythonJson::render(screens, false, false)?).ok()?
            }
        };
        let verdict = Self::smoke(summary, Some(*quick))?;
        let frame_data = serde_json::json!({
            "discover": true, "bundle_root": input.get("bundle_root")?.as_str()?,
            "scale": scale.as_float()?, "screens": screens,
        });
        let frames = frames::analyze(&frame_data, true)?;
        Self::result_output(&verdict, &frames, *quick)
    }

    fn result_output(
        verdict: &serde_json::Value,
        frames: &serde_json::Value,
        quick: bool,
    ) -> Option<serde_json::Value> {
        let problems = verdict["problems"].as_array()?;
        let mut failures = Vec::new();
        if !problems.is_empty() {
            let messages = problems
                .iter()
                .map(|p| Some(Value::String(p.as_str()?.to_owned())))
                .collect::<Option<Vec<_>>>()?;
            failures.push(format!(
                "schema violations: {}",
                PythonJson::repr(&Value::Array(messages))
            ));
        }
        for failure in frames["failures"].as_array()? {
            failures.push(failure.as_str()?.to_owned());
        }
        let svg_count = frames["svg_count"].as_u64()?;
        if !quick && svg_count == 0 {
            failures.push("no vector SVG assets exported (asset split broken?)".into());
        }
        for failure in verdict["coverage_failures"].as_array()? {
            failures.push(failure.as_str()?.to_owned());
        }
        let stdout = format!(
            "{}\nframes={} (for example: {}) assets: svg={svg_count} png={}\n",
            verdict["report"].as_str()?,
            frames["frames"].as_array()?.len(),
            frames["sample"].as_str()?,
            frames["png_count"].as_u64()?
        );
        let mut after_cleanup = String::new();
        let code = if failures.is_empty() {
            after_cleanup.push_str("LIVE SMOKE PASS ✅\n");
            0
        } else {
            after_cleanup.push_str("LIVE SMOKE FAILURES:\n");
            for failure in failures {
                after_cleanup.push_str(&format!(" - {failure}\n"));
            }
            1
        };
        Self::receipt(
            serde_json::json!({"stdout":stdout,"code":code,"after_cleanup":after_cleanup}),
        )
    }

    fn smoke(summary: &Value, quick: Option<bool>) -> Option<serde_json::Value> {
        let problems = FigmaValidation::validate(summary)?;
        let coverage = FigmaCoverage::compute(summary)?;
        let report = FigmaReport::render(&coverage, &problems)?;
        let count = |value: &Value| match value {
            Value::Number(Number::Integer(digits)) => digits.parse::<u64>().ok(),
            _ => None,
        };
        let screens = count(&coverage["screens"])?;
        let layout = count(&coverage["layoutNodes"]["total"])?;
        let fills = count(&coverage["assets"]["imageFillTotal"])?;
        let recovered = count(&coverage["assets"]["imageFillWithPath"])?;
        if let Some(quick) = quick {
            let mut failures = Vec::new();
            if screens > 0 && layout == 0 {
                failures.push("layout coverage is empty for a non-empty handoff".to_owned());
            }
            if !quick && fills > 0 {
                let percent = u128::from(recovered) * 100 / u128::from(fills);
                if percent < 100 {
                    failures.push(format!(
                        "image-fill recovery {recovered}/{fills} ({percent}%) < 100%"
                    ));
                }
            }
            return Self::receipt(serde_json::json!({
                "problems": problems, "report": report, "coverage_failures": failures,
            }));
        }
        Self::receipt(serde_json::json!({
            "problems": problems,
            "report": report,
            "screens": screens,
            "layout_total": layout,
            "image_fill_total": fills,
            "image_fill_with_path": recovered,
        }))
    }

    pub(crate) fn probe(
        request: &serde_json::Value,
        root: &std::path::Path,
    ) -> Option<serde_json::Value> {
        let path = Self::bound_input(request, root, "path")?;
        if !std::path::Path::new(path).is_file() {
            return None;
        }
        // evaluate rechecks the opened inode and declines device/descriptor
        // aliases before reading. A declined probe must leave streams untouched.
        let result = Self::evaluate(&OsString::from(path))?;
        Self::receipt(serde_json::json!({
            "code": result.code, "stdout": result.stdout, "stderr": result.stderr,
        }))
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
