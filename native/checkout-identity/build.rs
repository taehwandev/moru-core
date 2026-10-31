use std::{env, path::PathBuf, process::Command};

fn main() {
    let package = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let output = PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("pretool_contract.rs");
    let status = Command::new("python3")
        .arg(package.join("pretool_contract.py"))
        .arg("--emit")
        .arg(output)
        .status()
        .expect("native build requires Python for static source-contract generation");
    assert!(
        status.success(),
        "pretool source-contract generation failed"
    );
    println!("cargo:rerun-if-changed=pretool_contract.py");
}
