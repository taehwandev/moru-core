//! owner: DispatchGuardian private bounded command/env ingress and same-PID exec;
//! allowed imports: existing PythonJson, std and libc; forbidden imports: shell
//! fallback, new processes, admission and retries; callers/tests: guardian/gate;
//! verification: sibling payload and command-search tests; parent real worker tests.
use super::{DispatchGuardian, LIMIT};
use crate::python_json::{PythonJson, Value};
use std::{
    ffi::CString,
    io::{self, BufRead},
    os::{fd::AsRawFd, unix::ffi::OsStrExt},
    ptr,
};

impl DispatchGuardian {
    pub(super) fn message(reader: impl BufRead) -> io::Result<Option<Value>> {
        let mut raw = Vec::new();
        reader.take(LIMIT as u64 + 1).read_until(b'\n', &mut raw)?;
        if raw.last() != Some(&b'\n') || raw.len() > LIMIT {
            return Ok(None);
        }
        let text = std::str::from_utf8(&raw).map_err(|_| Self::invalid())?;
        PythonJson::parse(text).map(Some).ok_or_else(Self::invalid)
    }

    pub(super) fn request(value: &Value) -> io::Result<(Vec<String>, Vec<(String, String)>)> {
        let row = value.as_object().ok_or_else(Self::invalid)?;
        if row.len() != 2 {
            return Err(Self::invalid());
        }
        let command = Self::command(row.get("command").ok_or_else(Self::invalid)?)?;
        let environment = row
            .get("env")
            .and_then(Value::as_object)
            .ok_or_else(Self::invalid)?;
        let environment = environment
            .iter()
            .map(|(key, value)| {
                if key.contains(['\0', '=']) {
                    return Err(Self::invalid());
                }
                let value = value
                    .as_str()
                    .filter(|text| !text.contains('\0'))
                    .ok_or_else(Self::invalid)?;
                Ok((key.clone(), value.to_owned()))
            })
            .collect::<io::Result<Vec<_>>>()?;
        Ok((command, environment))
    }

    pub(super) fn gate() -> io::Result<i32> {
        let Some(message) = Self::message(std::io::stdin().lock())? else {
            return Ok(130);
        };
        let command = Self::command(&message)?;
        let arguments = command
            .iter()
            .map(|item| CString::new(item.as_bytes()).map_err(|_| Self::invalid()))
            .collect::<io::Result<Vec<_>>>()?;
        let path =
            std::env::var_os("PATH").unwrap_or_else(|| env!("MORU_PYTHON_DEFAULT_PATH").into());
        let candidates = Self::exec_candidates(arguments[0].as_bytes(), path.as_bytes())?;
        let environment = std::env::vars_os()
            .map(|(key, value)| {
                let mut raw = key.as_bytes().to_vec();
                raw.push(b'=');
                raw.extend_from_slice(value.as_bytes());
                CString::new(raw).map_err(|_| Self::invalid())
            })
            .collect::<io::Result<Vec<_>>>()?;
        let mut argv: Vec<_> = arguments.iter().map(|value| value.as_ptr()).collect();
        argv.push(ptr::null());
        let mut envp: Vec<_> = environment.iter().map(|value| value.as_ptr()).collect();
        envp.push(ptr::null());
        let null = std::fs::File::open("/dev/null")?;
        if unsafe { libc::dup2(null.as_raw_fd(), 0) } < 0 {
            return Err(io::Error::last_os_error());
        }
        drop(null);
        // A direct private gate also isolates inherited descriptors. The normal
        // self-spawn has already closed these before exec of the gate binary.
        for fd in Self::descriptors()? {
            unsafe {
                libc::close(fd);
            }
        }
        unsafe {
            // CPython's gate ignores these signals before os.execvpe; preserve
            // that inherited worker behavior rather than Rust's execvp fallback.
            libc::signal(libc::SIGPIPE, libc::SIG_IGN);
            libc::signal(libc::SIGXFSZ, libc::SIG_IGN);
            for candidate in candidates {
                libc::execve(candidate.as_ptr(), argv.as_ptr(), envp.as_ptr());
            }
        }
        Ok(127)
    }

    fn exec_candidates(program: &[u8], path: &[u8]) -> io::Result<Vec<CString>> {
        let value = |bytes| CString::new(bytes).map_err(|_| Self::invalid());
        if program.contains(&b'/') {
            return Ok(vec![value(program.to_vec())?]);
        }
        path.split(|byte| *byte == b':')
            .map(|directory| {
                let mut candidate = directory.to_vec();
                if !candidate.is_empty() && !candidate.ends_with(b"/") {
                    candidate.push(b'/');
                }
                candidate.extend_from_slice(program);
                value(candidate)
            })
            .collect()
    }
}

#[cfg(test)]
#[path = "command_tests.rs"]
mod tests;
