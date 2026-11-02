use std::env;
use std::ffi::OsString;
use std::io::{self, Write};
use std::os::unix::process::CommandExt;
use std::process::{exit, Command};

use moru_checkout_identity::CheckoutIdentity;

mod callback_replay;
mod callback_state;
mod cards_identity;
mod cards_process;
mod cards_store;
mod discovery_candidates;
mod discovery_fs;
mod discovery_process;
mod discovery_registry;
mod discovery_search;
#[allow(dead_code)] // Shared source; this crate only uses the status adapter.
mod gitrun;
mod launcher_backend;
mod mailbox_process;
mod mailbox_state;
mod next_process;
mod next_verification;
mod pretool_files;
mod pretool_guard;
mod pretool_process;
mod pretool_query;
mod pretool_transcript;
mod status_process;
mod status_snapshot;
mod status_state;
mod statusline;
mod statusline_chain;
mod statusline_process;
mod stop_process;
mod stop_state;
#[allow(dead_code)] // Git text decoding shares the library's text contract.
mod text;
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

    if args.first().is_some_and(|a| a == "work-cards") {
        finish(cards_process::CardsProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "project-discover") {
        let code = discovery_process::DiscoveryProcess::run(&launcher, &args);
        if args.get(1).is_some_and(|a| a == "--native-probe") {
            exit(code);
        }
        finish(code);
    }

    if args.first().is_some_and(|a| a == "agent-os-status") {
        finish(status_process::StatusProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "next") {
        finish(next_process::NextProcess::run(&launcher, &args));
    }

    if args
        .first()
        .is_some_and(|a| a == "claude-stop-gate" || a == "codex-stop-gate")
    {
        finish(stop_process::StopProcess::run(&launcher, &args));
    }

    if args.first().is_some_and(|a| a == "mailbox-hook") {
        finish(mailbox_process::MailboxProcess::run(&launcher, &args));
    }

    if args
        .first()
        .is_some_and(|a| a == "claude-pretool-gate" || a == "codex-pretool-gate")
    {
        finish(pretool_process::PretoolProcess::run(&launcher, &args));
    }

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
