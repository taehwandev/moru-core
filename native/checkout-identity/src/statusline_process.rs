//! One-shot statusline adapter. Owner: input/selection/output; no policy reads.
//! Imports: std, pure Renderer, Chain. Callers/tests: launcher, native statusline.
use crate::statusline::Renderer;
use crate::statusline_chain::Chain;
use std::env;
use std::ffi::OsString;
use std::io::{self, Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};

pub(crate) struct StatuslineProcess;

impl StatuslineProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(chain) = Self::chain(&args[1..]) else {
            crate::exec_python(launcher, args)
        };
        let Some(home) = Self::home() else {
            crate::exec_python(launcher, args)
        };
        // A different root can supply a different Python implementation.
        // Select compatibility before consuming stdin; never override it.
        if !Self::same_root(launcher, &home)
            || env::var_os("PYTHONIOENCODING").is_some()
            || env::var("PYTHONUTF8").is_ok_and(|s| s == "0")
        {
            crate::exec_python(launcher, args)
        }
        let color = match env::var("NO_COLOR") {
            Ok(value) => Renderer::strip(&value).is_empty(),
            Err(env::VarError::NotPresent) => true,
            Err(_) => crate::exec_python(launcher, args),
        };
        let mut raw = Vec::new();
        if io::stdin().read_to_end(&mut raw).is_err() {
            raw.clear(); // The Python reader treats read errors as empty input.
        }
        let Ok(text) = std::str::from_utf8(&raw) else {
            return Self::python_input(launcher, args, &raw);
        };
        let text = Self::newlines(text);
        let Some(mine) = Renderer::render(&text, &home, color) else {
            return Self::python_input(launcher, args, &raw);
        };
        let chained = match Chain::run(&chain, text) {
            Ok(value) => value,
            Err(()) => return 1, // Do not replay a chain after a decode failure.
        };
        let line = [mine.as_str(), Renderer::strip(&chained)]
            .into_iter()
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join("  ");
        match io::stdout()
            .lock()
            .write_all(line.as_bytes())
            .and_then(|_| io::stdout().flush())
        {
            Ok(()) => 0,
            Err(_) => 1,
        }
    }

    fn chain(args: &[OsString]) -> Option<String> {
        match args {
            [] => Some(String::new()),
            [flag, value] if flag == "--chain" && !value.to_str()?.starts_with('-') => {
                Some(value.to_str()?.to_owned())
            }
            [flag] => flag.to_str()?.strip_prefix("--chain=").map(str::to_owned),
            _ => None,
        }
    }

    fn home() -> Option<String> {
        let home = env::var("HOME").ok()?;
        if !home.starts_with('/')
            || home.contains("//")
            || (home.len() > 1 && home.ends_with('/'))
            || home.split('/').any(|part| part == "." || part == "..")
        {
            return None;
        }
        Some(home)
    }

    fn same_root(launcher: &OsString, home: &str) -> bool {
        let Some(base) = Path::new(launcher).parent().and_then(Path::parent) else {
            return false;
        };
        let Ok(pointer) = std::fs::read_to_string(base.join("moru-root")) else {
            return false;
        };
        let Ok(root) = Path::new(pointer.trim()).canonicalize() else {
            return false;
        };
        if !["AGENTS.md", "index.md", "scripts/workflow.py"]
            .iter()
            .all(|p| root.join(p).exists())
        {
            return false;
        }
        match env::var("MORU_HOME") {
            Ok(value) if !value.trim().is_empty() => Path::new(value.trim())
                .canonicalize()
                .is_ok_and(|p| p == root),
            Err(env::VarError::NotUnicode(_)) => false,
            _ => base.canonicalize().ok() == Path::new(home).join(".moru").canonicalize().ok(),
        }
    }

    fn python_input(launcher: &OsString, args: &[OsString], raw: &[u8]) -> i32 {
        let Ok(mut child) = Command::new("python3")
            .arg(launcher)
            .args(args)
            .stdin(Stdio::piped())
            .spawn()
        else {
            return 127;
        };
        // Reading the buffered input is safe: no chain or output ran yet.
        // Even if the Python parser exits early, reap it and retain its status.
        if let Some(mut pipe) = child.stdin.take() {
            let _ = pipe.write_all(raw);
        }
        match child.wait() {
            Ok(status) => status.code().unwrap_or(1),
            Err(_) => 1,
        }
    }

    pub(crate) fn newlines(text: &str) -> String {
        text.replace("\r\n", "\n").replace('\r', "\n")
    }
}
