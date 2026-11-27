//! owner: token-absent Figma live smoke ingress; allowed imports: callback guard,
//! encoding, process environment and stdout; forbidden imports: network, extraction;
//! callers/tests: public launcher and native Figma smoke entry fixtures;
//! verification: CLI skip bytes and pre-effect Python delegation.
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding};
use std::{ffi::OsString, io::Write};

fn token_name(args: &[OsString]) -> Option<&str> {
    let mut name = "FIGMA_TOKEN";
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        let arg = arg.to_str()?;
        if arg == "--quick" {
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
            "--url" => {}
            "--token-env"
                if !value.is_empty()
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b == b'_') =>
            {
                name = value
            }
            "--scale"
                if value
                    .bytes()
                    .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b))
                    && value.parse::<f64>().is_ok() => {}
            _ => return None,
        }
    }
    Some(name)
}

pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
    let Some(name) = token_name(&args[1..]) else {
        crate::exec_python(launcher, args)
    };
    if CallbackGuard::root(launcher, "git").is_none()
        || !PythonEncoding::utf8()
        || std::env::var_os("PYTHONIOENCODING").is_some()
        || std::env::var_os(name).is_some_and(|value| !value.is_empty())
    {
        crate::exec_python(launcher, args);
    }
    let output = format!("SKIP: {name} is not set — live smoke needs network + token.\n");
    i32::from(
        std::io::stdout()
            .lock()
            .write_all(output.as_bytes())
            .is_err(),
    )
}
