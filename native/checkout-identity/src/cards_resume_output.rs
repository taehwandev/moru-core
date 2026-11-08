//! owner: CardResumeOutput; allowed imports: std/libc/PythonText, terminal detection and frozen Python IO profile;
//! forbidden imports: input reads, providers, state writes; callers/tests: resume picker,
//! closed-pipe and long-menu CLI parity prove buffering, effects and final status.
use crate::cards_resume_terminal::CardResumeTerminal;
use crate::python_text::PythonText;
use std::{
    ffi::CStr,
    io::{self, Write},
    mem,
};

pub(crate) struct CardResumeOutput {
    text: Vec<u8>,
    binary: Vec<u8>,
    capacity: usize,
    line_buffered: bool,
}

impl CardResumeOutput {
    pub(crate) fn new() -> io::Result<Self> {
        let mut stat: libc::stat = unsafe { mem::zeroed() };
        if unsafe { libc::fstat(1, &mut stat) } != 0 {
            return Err(io::Error::last_os_error());
        }
        let minimum: usize = env!("MORU_PYTHON_IO_BUFFER").parse().unwrap();
        Ok(Self {
            text: Vec::new(),
            binary: Vec::new(),
            capacity: minimum.max((stat.st_blksize.max(0) as usize).min(8 * 1024 * 1024)),
            line_buffered: unsafe { libc::isatty(1) } == 1,
        })
    }

    pub(crate) fn print(&mut self, text: &str) -> io::Result<()> {
        self.write_text(text.as_bytes())?;
        self.write_text(b"\n")
    }

    pub(crate) fn prompt(&mut self) -> io::Result<()> {
        if CardResumeTerminal::active() {
            let _ = self.flush();
            // PyOS_StdioReadline prints its prompt on stderr and ignores the
            // C stream's write error; this differs from noninteractive input.
            let _ = io::stderr().write_all(b"> ");
            return Ok(());
        }
        self.write_text(b"> ")?;
        // CPython input() ignores flush failures, but not prompt-write failures.
        // An explicit choice can therefore still dispatch with a closed stdout.
        let _ = self.flush();
        Ok(())
    }

    pub(crate) fn finish(&mut self, status: i32) -> i32 {
        if self.flush_warning() {
            std::process::exit(120);
        }
        status
    }

    pub(crate) fn flush_warning(&mut self) -> bool {
        if let Err(error) = self.flush() {
            let name = match error.raw_os_error() {
                Some(libc::EPIPE | libc::ESHUTDOWN) => "BrokenPipeError",
                Some(libc::EACCES | libc::EPERM) => "PermissionError",
                Some(libc::EBADF) => "OSError",
                _ => "OSError",
            };
            let detail = format!("{name}: {}", Self::os_error(&error, None));
            let warning: String =
                serde_json::from_str(env!("MORU_PYTHON_FLUSH_ERROR_JSON")).unwrap();
            let warning = warning.replace("BrokenPipeError: [Errno 32] Broken pipe", &detail);
            let _ = io::stderr().write_all(warning.as_bytes());
            return true;
        }
        false
    }

    pub(crate) fn os_error(error: &io::Error, filename: Option<&str>) -> String {
        let Some(errno) = error.raw_os_error() else {
            return error.to_string();
        };
        let message = unsafe { CStr::from_ptr(libc::strerror(errno)) }.to_string_lossy();
        let suffix = filename
            .map(|name| format!(": {}", PythonText::repr(name)))
            .unwrap_or_default();
        format!("[Errno {errno}] {message}{suffix}")
    }

    fn write_text(&mut self, bytes: &[u8]) -> io::Result<()> {
        let chunk: usize = env!("MORU_PYTHON_IO_CHUNK").parse().unwrap();
        if !self.text.is_empty() && self.text.len() + bytes.len() > chunk {
            self.flush_text()?;
        }
        self.text.extend_from_slice(bytes);
        let line = self.line_buffered && bytes.iter().any(|b| matches!(b, b'\n' | b'\r'));
        if self.text.len() >= chunk || line {
            self.flush_text()?;
        }
        if line {
            self.flush_binary()?;
        }
        Ok(())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.flush_text()?;
        self.flush_binary()
    }

    fn flush_text(&mut self) -> io::Result<()> {
        let bytes = mem::take(&mut self.text);
        if self.binary.len() + bytes.len() > self.capacity {
            self.flush_binary()?;
        }
        let mut remaining = bytes.as_slice();
        while remaining.len() > self.capacity {
            let count = Self::write_raw(remaining)?;
            remaining = &remaining[count..];
        }
        self.binary.extend_from_slice(remaining);
        Ok(())
    }

    fn flush_binary(&mut self) -> io::Result<()> {
        while !self.binary.is_empty() {
            let count = Self::write_raw(&self.binary)?;
            self.binary.drain(..count);
        }
        Ok(())
    }

    fn write_raw(bytes: &[u8]) -> io::Result<usize> {
        let count = unsafe { libc::write(1, bytes.as_ptr().cast(), bytes.len()) };
        if count < 0 {
            return Err(io::Error::last_os_error());
        }
        if count == 0 {
            return Err(io::ErrorKind::WriteZero.into());
        }
        Ok(count as usize)
    }
}
