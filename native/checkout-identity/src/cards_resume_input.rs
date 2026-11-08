//! owner: CardResumeInput; allowed imports: std/libc/PythonText, scoped signal/IO and frozen integer
//! profile; forbidden imports: providers, files/state writes, auto-selection;
//! callers/tests: resume process; CLI/PTY tests prove cancel, EOF and signal restore.
use crate::{
    cards_resume_output::CardResumeOutput, cards_resume_signal::ResumeInterrupt,
    cards_resume_terminal::CardResumeTerminal, python_text::PythonText,
};
use std::{
    io,
    sync::mpsc::{self, Receiver, RecvTimeoutError},
    thread,
    time::Duration,
};

const INVALID: &str = "choose a number from the displayed task list";

pub(crate) struct CardResumeInput;

impl CardResumeInput {
    pub(crate) fn supported() -> bool {
        if serde_json::from_str::<String>(env!("MORU_PYTHON_FLUSH_ERROR_JSON"))
            .ok()
            .is_none_or(|value| value.is_empty())
        {
            return false;
        }
        let limit = env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
            .parse::<usize>()
            .unwrap_or(0);
        if limit > 0 && !env!("MORU_PYTHON_INT_LIMIT_ERROR").contains("<count>") {
            return false;
        }
        if std::env::var_os("PYTHONUTF8").is_some_and(|v| v == "1") {
            return Self::descriptors();
        }
        let locale = ["LC_ALL", "LC_CTYPE", "LANG"]
            .into_iter()
            .filter_map(|key| std::env::var(key).ok())
            .find(|v| !v.is_empty())
            .unwrap_or_default();
        let codec = locale.to_ascii_lowercase().replace('-', "");
        (codec.is_empty()
            || matches!(codec.as_str(), "c" | "posix" | "utf8")
            || codec.ends_with(".utf8"))
            && Self::descriptors()
    }

    fn descriptors() -> bool {
        (0..=2).all(|fd| {
            let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
            flags >= 0
                && if fd == 0 {
                    flags & libc::O_ACCMODE != libc::O_WRONLY
                } else {
                    flags & libc::O_ACCMODE != libc::O_RDONLY && flags & libc::O_NONBLOCK == 0
                }
        })
    }

    pub(crate) fn choose(
        count: usize,
        output: &mut CardResumeOutput,
    ) -> Result<Option<usize>, String> {
        let _interrupt =
            ResumeInterrupt::install().map_err(|e| CardResumeOutput::os_error(&e, None))?;
        let prompt = output.prompt();
        if ResumeInterrupt::interrupted() {
            Self::cancel(output);
        }
        prompt.map_err(|e| CardResumeOutput::os_error(&e, None))?;
        let bytes = Self::input(output).map_err(|e| CardResumeOutput::os_error(&e, None))?;
        if ResumeInterrupt::interrupted() {
            Self::cancel(output);
        }
        match bytes {
            None => Ok(None),
            Some(bytes) => match std::str::from_utf8(&bytes) {
                Ok(text) => Self::selection(text, count),
                // The supported POSIX stdin contract uses surrogateescape:
                // invalid UTF8 remains non-ASCII and fails before integer parsing.
                Err(_) => Err(INVALID.into()),
            },
        }
    }

    fn input(output: &mut CardResumeOutput) -> io::Result<Option<Vec<u8>>> {
        if unsafe { libc::fcntl(0, libc::F_GETFL) } & libc::O_NONBLOCK != 0 {
            return Self::line();
        }
        // Do not toggle the shared open-file description. The reader inherits a
        // blocked SIGINT; only the main thread owns cancellation and dispatch.
        let mask = ResumeInterrupt::block_current()?;
        let (sender, receiver) = mpsc::sync_channel(1);
        let reader = thread::Builder::new().spawn(move || {
            let _ = sender.send(Self::line());
        })?;
        drop(mask);
        let Some(result) = Self::receive(&receiver, || {}) else {
            Self::cancel(output);
        };
        reader
            .join()
            .map_err(|_| io::Error::other("stdin reader failed"))?;
        result
    }

    fn receive(
        receiver: &Receiver<io::Result<Option<Vec<u8>>>>,
        mut before_wait: impl FnMut(),
    ) -> Option<io::Result<Option<Vec<u8>>>> {
        loop {
            if ResumeInterrupt::interrupted() {
                return None;
            }
            before_wait();
            match receiver.recv_timeout(Duration::from_millis(50)) {
                Ok(value) => return Some(value),
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => {
                    return Some(Err(io::Error::other("stdin reader stopped")))
                }
            }
        }
    }

    fn cancel(output: &mut CardResumeOutput) -> ! {
        // Exit the CLI process, so a blocked owned reader cannot survive and
        // consume subsequent input or continue into provider execution.
        output.finish(0);
        std::process::exit(0);
    }

    fn selection(text: &str, count: usize) -> Result<Option<usize>, String> {
        let value = text.trim_matches(PythonText::whitespace);
        if value.is_empty() {
            return Ok(None);
        }
        if !value.is_ascii() || !value.bytes().all(|b| b.is_ascii_digit()) {
            return Err(INVALID.into());
        }
        let limit: usize = env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().unwrap_or(0);
        if limit > 0 && value.len() > limit {
            return Err(
                env!("MORU_PYTHON_INT_LIMIT_ERROR").replace("<count>", &value.len().to_string())
            );
        }
        let number = value
            .trim_start_matches('0')
            .parse::<usize>()
            .ok()
            .filter(|n| *n >= 1 && *n <= count)
            .ok_or_else(|| INVALID.to_owned())?;
        Ok(Some(number - 1))
    }

    fn line() -> io::Result<Option<Vec<u8>>> {
        if CardResumeTerminal::active() {
            return CardResumeTerminal::line();
        }
        let mut line = Vec::new();
        loop {
            // Match TextIOWrapper's ordinary 8KiB read-ahead: bytes already read
            // past this line stay consumed when the selected child inherits fd0.
            let mut chunk = [0u8; 8192];
            let read = unsafe { libc::read(0, chunk.as_mut_ptr().cast(), chunk.len()) };
            if read < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::WouldBlock {
                    return Ok((!line.is_empty()).then_some(line));
                }
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            let length = read as usize;
            if length == 0 {
                return Ok((!line.is_empty()).then_some(line));
            }
            let bytes = &chunk[..length];
            if let Some(end) = bytes.iter().position(|b| *b == b'\n') {
                line.extend_from_slice(&bytes[..end]);
                return Ok(Some(line));
            } else {
                line.extend_from_slice(bytes);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interrupt_after_flag_check_never_blocks_on_an_empty_channel() {
        let _lock = crate::cards_resume_signal::TEST_LOCK.lock().unwrap();
        let _interrupt = ResumeInterrupt::test_scope().unwrap();
        let (_sender, receiver) = mpsc::sync_channel(1);
        let start = std::time::Instant::now();
        assert!(CardResumeInput::receive(&receiver, || {
            unsafe {
                libc::raise(libc::SIGINT);
            }
        })
        .is_none());
        assert!(start.elapsed() < Duration::from_secs(1));
    }
    #[test]
    fn explicit_selection_only_ascii_decimal_and_python_whitespace() {
        for value in ["", " \t\u{2000}"] {
            assert_eq!(CardResumeInput::selection(value, 2), Ok(None));
        }
        for value in ["1", "00001", " \u{2000}1\r"] {
            assert_eq!(CardResumeInput::selection(value, 2), Ok(Some(0)));
        }
        for value in ["0", "00", "3", "-1", "+1", "١", "latest", "1_0", "1\0"] {
            assert_eq!(CardResumeInput::selection(value, 2), Err(INVALID.into()));
        }
    }
    #[test]
    fn integer_limit_uses_the_frozen_builder_profile_without_overflow() {
        let limit: usize = env!("MORU_PYTHON_INT_MAX_STR_DIGITS").parse().unwrap();
        if limit > 0 {
            assert_eq!(
                CardResumeInput::selection(&"1".repeat(limit + 1), 2),
                Err(env!("MORU_PYTHON_INT_LIMIT_ERROR")
                    .replace("<count>", &(limit + 1).to_string()))
            );
        } else {
            assert_eq!(
                CardResumeInput::selection(&("0".repeat(5000) + "1"), 2),
                Ok(Some(0))
            );
        }
        assert!(CardResumeInput::selection(&"9".repeat(100), 2).is_err());
    }
}
