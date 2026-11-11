//! owner: CardResumeTerminal; allowed imports: libc/std; forbidden imports: providers,
//! descriptor flag changes, prompt writes; callers/tests: resume input and terminal tests.
//! Contract: CPython v3.9.6 Parser/myreadline.c and Python/bltinmodule.c input path.
//! https://github.com/python/cpython/blob/v3.9.6/Parser/myreadline.c
//! https://github.com/python/cpython/blob/v3.9.6/Python/bltinmodule.c
use std::{io, ptr};

pub(crate) struct CardResumeTerminal;

impl CardResumeTerminal {
    pub(crate) fn active() -> bool {
        unsafe { libc::isatty(0) == 1 && libc::isatty(1) == 1 }
    }

    pub(crate) fn line() -> io::Result<Option<Vec<u8>>> {
        Self::fd_line(0)
    }

    fn fd_line(fd: libc::c_int) -> io::Result<Option<Vec<u8>>> {
        let stream = Stream::open(fd)?;
        Self::read(&stream)
    }

    fn read(stream: &Stream) -> io::Result<Option<Vec<u8>>> {
        let mut buffer = Vec::new();
        let mut used = 0usize;
        loop {
            let increment = Self::increment(used)?;
            let total = used.checked_add(increment).ok_or_else(Self::too_long)?;
            if buffer.len() < total {
                buffer
                    .try_reserve_exact(total - buffer.len())
                    .map_err(|_| io::Error::from_raw_os_error(libc::ENOMEM))?;
                buffer.resize(total, 0u8);
            }
            let target = unsafe { buffer.as_mut_ptr().add(used).cast::<libc::c_char>() };
            if !Self::gets(stream, target, increment as libc::c_int) {
                // EOF/error discards this attempt's partial bytes, retaining
                // only chunks whose fgets returned a non-null C string.
                buffer[used] = 0;
                break;
            }
            used += unsafe { libc::strlen(target) };
            if used != 0 && buffer[used - 1] == b'\n' {
                break;
            }
            // CPython's first-byte NUL case reads p[-1], an undefined C access.
            // Continue safely rather than reproduce an allocator-dependent read.
        }
        if used == 0 {
            return Ok(None);
        }
        // builtin_input drops the final byte even for a partial EOF/error line.
        used -= 1;
        if used != 0 && buffer[used - 1] == b'\r' {
            used -= 1;
        }
        buffer.truncate(used);
        Ok(Some(buffer))
    }

    fn increment(used: usize) -> io::Result<usize> {
        let increment = if used == 0 {
            100
        } else {
            used.checked_add(2).ok_or_else(Self::too_long)?
        };
        if increment > libc::c_int::MAX as usize {
            return Err(Self::too_long());
        }
        Ok(increment)
    }

    fn too_long() -> io::Error {
        io::Error::new(io::ErrorKind::InvalidData, "input line too long")
    }

    fn gets(stream: &Stream, target: *mut libc::c_char, length: libc::c_int) -> bool {
        loop {
            unsafe {
                libc::clearerr(stream.0);
            }
            Self::clear_errno();
            if !unsafe { libc::fgets(target, length, stream.0) }.is_null() {
                return true;
            }
            let error = io::Error::last_os_error().raw_os_error();
            if unsafe { libc::feof(stream.0) } != 0 {
                unsafe {
                    libc::clearerr(stream.0);
                }
                return false;
            }
            if error != Some(libc::EINTR) {
                return false;
            }
            // The parent owns SIGINT cancellation; this reader inherits it
            // blocked and otherwise retries fgets exactly after EINTR.
        }
    }

    fn clear_errno() {
        #[cfg(target_os = "macos")]
        unsafe {
            *libc::__error() = 0;
        }
        #[cfg(target_os = "linux")]
        unsafe {
            *libc::__errno_location() = 0;
        }
    }
}

struct Stream(*mut libc::FILE);
impl Stream {
    fn open(fd: libc::c_int) -> io::Result<Self> {
        let duplicate = unsafe { libc::dup(fd) };
        if duplicate < 0 {
            return Err(io::Error::last_os_error());
        }
        let file = unsafe { libc::fdopen(duplicate, b"r\0".as_ptr().cast()) };
        if file == ptr::null_mut() {
            let error = io::Error::last_os_error();
            unsafe {
                libc::close(duplicate);
            }
            return Err(error);
        }
        Ok(Self(file))
    }
}
impl Drop for Stream {
    fn drop(&mut self) {
        unsafe {
            libc::fclose(self.0);
        }
    }
}

#[cfg(test)]
#[path = "cards_resume_terminal_tests.rs"]
mod tests;
