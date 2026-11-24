//! owner: pre-effect mutation specification loading and validation.
//! allowed imports: bounded Python-compatible file, UTF-8, and JSON readers.
//! forbidden imports: target writes, subprocesses and workflow state.
//! callers/tests: mutation-check runner and CLI differential fixtures.
//! verification: source shapes, error text, and safe decline for unsupported profiles.
use crate::{
    python_input_file::{FileRead, PythonInputFile},
    python_json::{InputDiagnostic, PythonJson, Value},
    python_text::PythonUtf8,
    text::Text,
};
use std::{env, ffi::OsStr, path::Path};

pub(super) struct Entry {
    pub(super) label: String,
    pub(super) file: String,
    pub(super) old: String,
    pub(super) new: String,
}

pub(super) fn load(path: &Path, limit: u64) -> Option<Result<Vec<Entry>, String>> {
    let normalized = Text::norm_path(path.to_str()?);
    let bytes = match PythonInputFile::read(OsStr::new(&normalized), limit, false)? {
        FileRead::Bytes(bytes) => bytes,
        FileRead::Error(message) if normalized.is_ascii() && plain_locale() => {
            return Some(Err(message))
        }
        _ => return None,
    };
    let text = match PythonUtf8::decode(&bytes) {
        Ok(text) => Text::universal_newlines(text),
        Err(message) => return Some(Err(message)),
    };
    // 640 is the lowest positive Python integer-conversion limit. Defer values
    // above it and syntax diagnostics that vary by interpreter generation.
    let value = match PythonJson::parse_with_diagnostic(&text, Some(640), Some(false)) {
        Ok(value) => value?,
        Err(InputDiagnostic::Syntax(message)) => {
            return match PythonJson::parse_with_diagnostic(&text, Some(640), Some(true)) {
                Err(InputDiagnostic::Syntax(other)) if other == message => Some(Err(message)),
                _ => None,
            };
        }
        Err(_) => return None,
    };
    Some(entries(&value))
}

fn entries(value: &Value) -> Result<Vec<Entry>, String> {
    value
        .as_array()
        .ok_or("spec must be a list of mutants")?
        .iter()
        .enumerate()
        .map(|(index, row)| {
            if !row.is_object() {
                return Err(format!("mutant {index} is not an object"));
            }
            let field = |name| {
                row.get(name)
                    .and_then(Value::as_str)
                    .filter(|value| !value.is_empty())
                    .map(str::to_owned)
                    .ok_or_else(|| format!("mutant {index} is missing {name}"))
            };
            Ok(Entry {
                label: field("label")?,
                file: field("file")?,
                old: field("old")?,
                new: field("new")?,
            })
        })
        .collect()
}

fn plain_locale() -> bool {
    ["LC_ALL", "LC_MESSAGES", "LANG"]
        .into_iter()
        .find_map(|key| env::var_os(key).filter(|value| !value.is_empty()))
        .is_none_or(|value| {
            value
                .to_str()
                .and_then(|value| value.split(['.', '@']).next())
                .is_some_and(|value| matches!(value, "C" | "POSIX" | "en_US" | "en_GB"))
        })
}
