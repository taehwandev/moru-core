//! owner: ReactManifest; allowed imports: std, serde_json, private manifest modules;
//! forbidden imports: Python launchers; callers/tests: native launcher; verification: CLI parity.
#[path = "react_manifest_cli.rs"]
mod cli;
#[path = "react_manifest_io.rs"]
mod io;
#[path = "manifest_number.rs"]
mod number;
#[path = "manifest_object.rs"]
mod object;
#[path = "manifest_parser.rs"]
mod parser;
#[path = "react_manifest_validation.rs"]
mod validation;
#[path = "manifest_value.rs"]
mod value;
use self::{cli::ReactManifestCli, io::ManifestIo, validation::ManifestValidation as V};
use self::{parser::ManifestParser, value::ManifestValue as Value};
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
        let payload = ManifestParser::parse(&text)?;
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
}
