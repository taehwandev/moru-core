use std::{env, path::PathBuf, process::Command};

fn main() {
    println!("cargo:rerun-if-env-changed=PATH");
    let package = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let directory = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let output = directory.join("pretool_contract.rs");
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
    let status = Command::new("python3")
        .arg(package.join("status_contract.py"))
        .arg("--emit")
        .arg(directory.join("status_contract.rs"))
        .status()
        .expect("native build requires Python for status-contract generation");
    assert!(status.success(), "status-contract generation failed");
    println!("cargo:rerun-if-changed=status_contract.py");
    let status = Command::new("python3")
        .arg(package.join("next_contract.py"))
        .arg("--emit")
        .arg(directory.join("next_contract.rs"))
        .status()
        .expect("native build requires Python for next-advice contract generation");
    assert!(status.success(), "next-advice contract generation failed");
    println!("cargo:rerun-if-changed=next_contract.py");
    let status = Command::new("python3")
        .arg(package.join("figma_contract.py"))
        .arg("--emit")
        .arg(directory.join("figma_contract.rs"))
        .status()
        .expect("native build requires Python for Figma numeric contract generation");
    assert!(status.success(), "Figma numeric contract generation failed");
    println!("cargo:rerun-if-changed=figma_contract.py");
    let status = Command::new("python3")
        .arg(package.join("json_contract.py"))
        .arg("--emit")
        .arg(directory.join("json_contract.rs"))
        .status()
        .expect("native build requires Python for JSON diagnostic contract generation");
    assert!(
        status.success(),
        "JSON diagnostic contract generation failed"
    );
    println!("cargo:rerun-if-changed=json_contract.py");
    emit_iso_midnight_profile();
}

fn emit_iso_midnight_profile() {
    const PROBE: &str = r#"
from datetime import datetime

try:
    value = datetime.fromisoformat('2000-02-29T24:00:00')
except ValueError:
    print('reject')
else:
    assert value == datetime(2000, 3, 1)
    print('rollover')
"#;
    let output = Command::new("python3")
        .args(["-I", "-c", PROBE])
        .output()
        .expect("native build requires the Python ISO midnight behavior probe");
    assert!(
        output.status.success(),
        "ISO midnight behavior probe failed"
    );
    let profile = match output.stdout.as_slice() {
        b"reject\n" => "reject",
        b"rollover\n" => "rollover",
        _ => panic!("unexpected ISO midnight behavior probe result"),
    };
    println!("cargo:rustc-env=MORU_ISO_MIDNIGHT={profile}");
}
