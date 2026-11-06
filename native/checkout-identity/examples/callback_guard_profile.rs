//! Developer-only timing of the unchanged callback guard, never an admission path.
#![allow(dead_code)]

#[path = "../src/pretool_guard.rs"]
mod pretool_guard;
#[path = "../src/python_text.rs"]
mod python_text;
#[path = "../src/python_float.rs"]
mod python_float;
#[path = "../src/python_json.rs"]
mod python_json;
#[path = "../src/statusline/mod.rs"]
mod statusline;

fn main() {
    let launcher = std::env::args_os()
        .nth(1)
        .expect("fixture launcher required");
    let started = std::time::Instant::now();
    let valid = pretool_guard::CallbackGuard::root(&launcher, "cat").is_some();
    println!(
        "{}",
        serde_json::json!({"valid": valid, "guard_ms": started.elapsed().as_secs_f64() * 1000.0})
    );
    if !valid {
        std::process::exit(1);
    }
}
