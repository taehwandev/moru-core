use std::io::{self, Write};
use std::process::ExitCode;

use moru_checkout_identity::CheckoutIdentity;

const USAGE: &str = "Usage: moru-checkout-identity\n\
Reads NDJSON requests on stdin and writes one NDJSON response per line on stdout.\n\
Request: {\"schema_version\":1,\"root\":\"/absolute/path\"}\n";

fn main() -> ExitCode {
    let mut args = std::env::args_os().skip(1);
    match args.next() {
        None => {}
        Some(arg) if arg == "--help" && args.next().is_none() => {
            return match io::stdout().write_all(USAGE.as_bytes()) {
                Ok(()) => ExitCode::SUCCESS,
                Err(_) => ExitCode::from(1),
            };
        }
        Some(_) => {
            let _ = io::stderr().write_all(USAGE.as_bytes());
            return ExitCode::from(2);
        }
    }

    let stdin = io::stdin();
    let stdout = io::stdout();
    match CheckoutIdentity::serve(stdin.lock(), stdout.lock()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            let _ = writeln!(io::stderr(), "moru-checkout-identity: {err}");
            ExitCode::from(1)
        }
    }
}
