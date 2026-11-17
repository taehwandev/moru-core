//! owner: DispatchGuardian content-free ordered receipt read/atomic persistence;
//! allowed imports: existing PythonJson values/numbers, serde quoting, std/libc;
//! forbidden imports: admission decisions, scheduler writes, argv/env persistence;
//! callers/tests: guardian transitions; sibling byte/fsync-path/symlink tests;
//! verification: immutable Python dump spacing/order/ASCII and parent failure parity.
use super::DispatchGuardian;
use crate::python_json::{Number, PythonJson, Value};
use std::{
    ffi::OsString,
    fs::{self, File},
    io::{self, Write},
    os::{
        fd::FromRawFd,
        unix::ffi::{OsStrExt, OsStringExt},
    },
    path::Path,
};

impl DispatchGuardian {
    pub(super) fn read_receipt(path: &Path) -> io::Result<Value> {
        let text = fs::read_to_string(path)?;
        PythonJson::parse(&text)
            .filter(Value::is_object)
            .ok_or_else(Self::invalid)
    }

    pub(super) fn save_receipt(
        path: &Path,
        state: &Value,
        phase: &str,
        code: Option<i32>,
    ) -> io::Result<()> {
        let mut state = state.as_object().ok_or_else(Self::invalid)?.clone();
        if state.iter().any(|(key, _)| {
            ![
                "run_id",
                "task_id",
                "attempt",
                "execution_id",
                "state",
                "returncode",
            ]
            .contains(&key.as_str())
        }) {
            return Err(Self::invalid());
        }
        state.insert("state".into(), Value::String(phase.into()));
        if let Some(code) = code {
            state.insert(
                "returncode".into(),
                Value::Number(Number::Integer(code.to_string())),
            );
        }
        let text = Self::json(&Value::Object(state))?;
        Self::not_symlink(path)?;
        let parent = path
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        let mut template = parent
            .join(".execution-XXXXXX")
            .as_os_str()
            .as_bytes()
            .to_vec();
        template.push(0);
        let fd = unsafe { libc::mkstemp(template.as_mut_ptr().cast()) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        template.pop();
        let temporary = std::path::PathBuf::from(OsString::from_vec(template));
        let result = (|| {
            let mut file = unsafe { File::from_raw_fd(fd) };
            file.write_all(text.as_bytes())?;
            file.flush()?;
            file.sync_all()?;
            drop(file);
            Self::not_symlink(path)?;
            fs::rename(&temporary, path)?;
            File::open(parent)?.sync_all()
        })();
        match fs::remove_file(&temporary) {
            Err(error) if error.kind() != io::ErrorKind::NotFound => return Err(error),
            _ => {}
        }
        result
    }

    fn not_symlink(path: &Path) -> io::Result<()> {
        match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.file_type().is_symlink() => Err(Self::invalid()),
            Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
            _ => Ok(()),
        }
    }
}

impl DispatchGuardian {
    pub(super) fn json(value: &Value) -> io::Result<String> {
        Ok(match value {
            Value::Null => "null".into(),
            Value::Bool(value) => if *value { "true" } else { "false" }.into(),
            Value::Number(Number::Integer(value)) => value.clone(),
            Value::Number(Number::Float(value)) if value.is_nan() => "NaN".into(),
            Value::Number(Number::Float(value)) if *value == f64::INFINITY => "Infinity".into(),
            Value::Number(Number::Float(value)) if *value == f64::NEG_INFINITY => {
                "-Infinity".into()
            }
            Value::Number(Number::Float(value)) => Number::float(*value),
            Value::String(value) => Self::quote(value)?,
            Value::Array(values) => format!(
                "[{}]",
                values
                    .iter()
                    .map(Self::json)
                    .collect::<io::Result<Vec<_>>>()?
                    .join(", ")
            ),
            Value::Object(values) => format!(
                "{{{}}}",
                values
                    .iter()
                    .map(|(key, value)| {
                        Ok(format!("{}: {}", Self::quote(key)?, Self::json(value)?))
                    })
                    .collect::<io::Result<Vec<_>>>()?
                    .join(", ")
            ),
        })
    }

    fn quote(value: &str) -> io::Result<String> {
        let escaped = serde_json::to_string(value).map_err(|_| Self::invalid())?;
        let mut ascii = String::new();
        for character in escaped.chars() {
            if character >= '\u{7f}' {
                for unit in character.encode_utf16(&mut [0; 2]) {
                    ascii.push_str(&format!("\\u{unit:04x}"));
                }
            } else {
                ascii.push(character);
            }
        }
        Ok(ascii)
    }
}

#[cfg(test)]
#[path = "receipt_tests.rs"]
mod tests;
