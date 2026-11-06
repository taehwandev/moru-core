//! owner: ReactManifest; allowed imports: std, serde_json, private manifest modules;
//! forbidden imports: Python launchers; callers/tests: native launcher; verification: CLI parity.
#[path = "react_manifest_cli.rs"]
mod cli;
#[path = "react_manifest_io.rs"]
mod io;
#[path = "react_manifest_validation.rs"]
mod validation;
use self::{cli::ReactManifestCli, io::ManifestIo, validation::ManifestValidation as V};
use serde_json::Value;
use std::{ffi::OsString, fs, path::Path};
pub struct ReactManifest;
impl ReactManifest {
    /// None is a pre-effect decline for Python exceptions/coercions not represented here.
    pub fn run(root: &Path, args: &[OsString]) -> Option<i32> {
        let options = ReactManifestCli::parse(root, args)?;
        if let Some(status) = options.exit {
            return Some(status);
        }
        let ReactManifestCli {
            manifest,
            source,
            remote,
            ..
        } = options;
        // Python decodes both remote pipes and applies communicate()'s timeout.
        // Preserve those exception/pipe-lifetime semantics before any remote effect.
        if remote {
            return None;
        }
        let text = fs::read_to_string(manifest).ok()?;
        if !Self::exact_integers(&text) {
            return None;
        }
        let payload: Value = serde_json::from_str(&text).ok()?;
        let mut failures = V::failures(&payload, root)?;
        if let Some(source) = source {
            failures.extend(ManifestIo::source_failures(&payload, &source)?);
        }
        if !failures.is_empty() {
            for f in failures {
                println!("FAIL: {f}");
            }
            return Some(1);
        }
        let entries = payload["skills"].as_array().expect("validated skills");
        let installable = entries
            .iter()
            .filter_map(Value::as_object)
            .filter(|e| e.get("installable").is_some_and(V::truthy))
            .count();
        println!("OK: React/RN external skill manifest covers {} SKILL.md files ({} installable, {} nested)",entries.len(),installable,entries.len()-installable);
        Some(0)
    }
    // serde_json otherwise rounds integers beyond its 64-bit range into floats.
    fn exact_integers(text: &str) -> bool {
        let bytes = text.as_bytes();
        let mut i = 0;
        let mut quoted = false;
        while i < bytes.len() {
            match bytes[i] {
                b'\\' if quoted => {
                    i += 2;
                    continue;
                }
                b'"' => quoted = !quoted,
                b'-' | b'0'..=b'9' if !quoted => {
                    let start = i;
                    i += 1;
                    while i < bytes.len()
                        && matches!(bytes[i], b'0'..=b'9' | b'.' | b'e' | b'E' | b'+' | b'-')
                    {
                        i += 1;
                    }
                    let n = &text[start..i];
                    // Python keeps JSON -0 as integer zero; serde preserves a float sign.
                    if n == "-0" {
                        return false;
                    }
                    if !n.contains(['.', 'e', 'E'])
                        && n.parse::<i64>().is_err()
                        && n.parse::<u64>().is_err()
                    {
                        return false;
                    }
                    continue;
                }
                _ => {}
            }
            i += 1;
        }
        true
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_remote_declines_before_work() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        assert_eq!(ReactManifest::run(&root, &[]), Some(0));
        for flag in ["--remote-check", "--remote", "--r"] {
            assert_eq!(ReactManifest::run(&root, &[OsString::from(flag)]), None);
        }
    }
    #[test]
    fn negative_integer_zero_declines_without_changing_float_or_string() {
        assert!(!ReactManifest::exact_integers("{\"owner\":-0}"));
        assert!(ReactManifest::exact_integers(
            "{\"owner\":\"-0\",\"float\":-0.0,\"exponent\":-0e0}"
        ));
    }
    #[test]
    fn oversized_integer_declines_without_rounding() {
        assert!(!ReactManifest::exact_integers(
            "{\"owner\":18446744073709551616}"
        ));
        assert!(ReactManifest::exact_integers(
            "{\"owner\":\"18446744073709551616\",\"float\":1e30}"
        ));
    }
}
