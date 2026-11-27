//! owner: Figma live smoke argument admission; allowed imports: callback guard,
//! encoding, process environment and stdout; forbidden imports: network, extraction;
//! callers/tests: public launcher and native Figma smoke entry fixtures;
//! verification: CLI skip bytes and pre-effect Python delegation.
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding};
use std::{ffi::OsString, io::Write};

#[path = "figma_smoke_orchestration.rs"]
mod orchestration;

struct Options<'a> {
    name: &'a str,
    url: Option<&'a str>,
    quick: bool,
    scale: f64,
}

fn options(args: &[OsString]) -> Option<Options<'_>> {
    let mut options = Options {
        name: "FIGMA_TOKEN",
        url: None,
        quick: false,
        scale: 3.0,
    };
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        let arg = arg.to_str()?;
        if arg == "--quick" {
            options.quick = true;
            continue;
        }
        let (key, attached) = arg
            .split_once('=')
            .map_or((arg, None), |(k, v)| (k, Some(v)));
        let value = match attached {
            Some(value) => value,
            None => {
                let value = args.next()?.to_str()?;
                if value.starts_with('-') {
                    return None;
                }
                value
            }
        };
        match key {
            "--url" => options.url = Some(value),
            "--token-env"
                if !value.is_empty()
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_') =>
            {
                options.name = value
            }
            "--scale"
                if value
                    .bytes()
                    .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b)) =>
            {
                options.scale = value.parse::<f64>().ok()?
            }
            _ => return None,
        }
    }
    Some(options)
}

pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
    let Some(options) = options(&args[1..]) else {
        crate::exec_python(launcher, args)
    };
    let Some(root) = CallbackGuard::root(launcher, "git") else {
        crate::exec_python(launcher, args)
    };
    if !PythonEncoding::utf8() || !options.scale.is_finite() {
        crate::exec_python(launcher, args);
    }
    if !std::env::var_os(options.name).is_some_and(|value| !value.is_empty()) {
        let output = format!(
            "SKIP: {} is not set — live smoke needs network + token.\n",
            options.name
        );
        return i32::from(
            std::io::stdout()
                .lock()
                .write_all(output.as_bytes())
                .is_err(),
        );
    }
    let fallback = std::env::var("FIGMA_SMOKE_URL").ok();
    let Some(url) = options
        .url
        .or(fallback.as_deref())
        .filter(|s| !s.is_empty())
    else {
        crate::exec_python(launcher, args)
    };
    let Some(code) = orchestration::run(&root, &options, url) else {
        crate::exec_python(launcher, args)
    };
    code
}
