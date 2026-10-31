use std::env;
use std::ffi::OsString;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::process::{exit, Command};

use moru_checkout_identity::CheckoutIdentity;

mod launcher_backend;
mod statusline;
mod statusline_chain;
mod statusline_process;
use launcher_backend::Backend;

const USAGE: &str = "usage: moru-native-launcher PYTHON_LAUNCHER [ARGS...]\n       moru-native-launcher PYTHON_LAUNCHER checkout-identity [--help]\n";
const CHECKOUT_USAGE: &str = "usage: moru-hook checkout-identity < requests.ndjson\n";

// Native handler exits are softened only under the existing hook convention.
fn finish(code: i32) -> ! {
    let soft = env::var_os("MORU_HOOK_SOFT_FAIL").map_or(false, |v| v == "1");
    exit(if code != 0 && soft { 0 } else { code })
}

// Replace the process with the legacy Python launcher; never returns.
fn exec_python(launcher: &OsString, args: &[OsString]) -> ! {
    let err = Command::new("python3").arg(launcher).args(args).exec();
    eprintln!("moru-native-launcher: failed to exec python3: {err}");
    exit(127)
}

fn native_checkout_identity(extra: &[OsString]) -> i32 {
    match extra {
        [] => {
            let stdin = io::stdin();
            let stdout = io::stdout();
            match CheckoutIdentity::serve(stdin.lock(), stdout.lock()) {
                Ok(()) => 0,
                Err(err) => {
                    eprintln!("moru-native-launcher: checkout-identity I/O error: {err}");
                    1
                }
            }
        }
        [flag] if flag == "--help" => {
            let mut out = io::stdout().lock();
            match out
                .write_all(CHECKOUT_USAGE.as_bytes())
                .and_then(|_| out.flush())
            {
                Ok(()) => 0,
                Err(err) => {
                    eprintln!("moru-native-launcher: failed to write usage: {err}");
                    1
                }
            }
        }
        _ => {
            eprintln!("moru-native-launcher: checkout-identity accepts no arguments except --help");
            2
        }
    }
}

fn main() {
    let mut argv = env::args_os().skip(1);
    let launcher = match argv.next() {
        Some(l) => l,
        None => {
            eprint!("moru-native-launcher: missing PYTHON_LAUNCHER\n{USAGE}");
            exit(2);
        }
    };
    let args: Vec<OsString> = argv.collect();

    if args
        .first()
        .map_or(false, |a| a == "claude-statusline" || a == "agy-statusline")
    {
        finish(statusline_process::StatuslineProcess::run(&launcher, &args));
    }

    if args.first().map_or(false, |a| a == "checkout-identity") {
        match Backend::from_env() {
            Backend::Python => exec_python(&launcher, &args),
            Backend::Unknown => {
                eprintln!("moru-native-launcher: unknown MORU_CHECKOUT_IDENTITY_BACKEND");
                finish(2);
            }
            Backend::Native => finish(native_checkout_identity(&args[1..])),
        }
    }

    exec_python(&launcher, &args)
}
