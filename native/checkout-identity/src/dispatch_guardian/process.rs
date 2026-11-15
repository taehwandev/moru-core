//! owner: DispatchGuardian self-spawn, lifeline and owned process-group lifetime;
//! allowed imports: std/libc and receipt command encoding; forbidden imports:
//! stored PID signaling, scheduler decisions, fallback and retries;
//! callers/tests: guardian; sibling FD/lock and parent crash/cancel scenarios;
//! verification: offline debug tests and real owned-temp process observations.
use super::DispatchGuardian;
use crate::python_json::Value;
use std::{
    ffi::{CString, OsString},
    fs,
    io::{self, Write},
    os::unix::{
        ffi::OsStrExt,
        process::{CommandExt, ExitStatusExt},
    },
    process::{Child, Command, ExitStatus, Stdio},
    thread,
    time::{Duration, Instant},
};

impl DispatchGuardian {
    pub(super) fn spawn_gate(
        guardian: &OsString,
        environment: &[(String, String)],
    ) -> io::Result<Child> {
        // Snapshot before Command creates its exec-error pipe. Filtering occurs
        // after ReadDir is dropped, so its recycled FD cannot close that pipe.
        let descriptors = Self::descriptors()?;
        let executable = std::env::current_exe()?;
        let program =
            CString::new(executable.as_os_str().as_bytes()).map_err(|_| Self::invalid())?;
        let guardian =
            CString::new(guardian.as_os_str().as_bytes()).map_err(|_| Self::invalid())?;
        let mode = CString::new("--dispatch-exec-gate").unwrap();
        let encoded = environment
            .iter()
            .map(|(key, value)| CString::new(format!("{key}={value}")).map_err(|_| Self::invalid()))
            .collect::<io::Result<Vec<_>>>()?;
        // Store addresses as usize so the captured immutable table is Send/Sync.
        // CString storage is captured too and survives until execve. No child
        // allocation is needed and Command's newly-created error pipe stays live.
        let mut envp: Vec<usize> = encoded.iter().map(|item| item.as_ptr() as usize).collect();
        envp.push(0);
        let mut command = Command::new(executable);
        command.env_clear().stdin(Stdio::piped());
        Self::isolate(&mut command, descriptors);
        unsafe {
            command.pre_exec(move || {
                let _storage = &encoded;
                let argv = [
                    program.as_ptr(),
                    guardian.as_ptr(),
                    mode.as_ptr(),
                    std::ptr::null(),
                ];
                libc::execve(program.as_ptr(), argv.as_ptr(), envp.as_ptr().cast());
                // Never reach std's sorted-environment exec or shell fallback.
                Err(io::Error::last_os_error())
            });
        }
        command.spawn()
    }

    fn isolate(command: &mut Command, descriptors: Vec<libc::c_int>) {
        unsafe {
            command.pre_exec(move || {
                if libc::setsid() < 0 {
                    return Err(io::Error::last_os_error());
                }
                for &fd in &descriptors {
                    libc::close(fd);
                }
                Ok(())
            });
        }
    }

    pub(super) fn release(child: &mut Child, command: &[String]) -> io::Result<()> {
        let message = Value::Array(command.iter().cloned().map(Value::String).collect());
        let mut line = Self::json(&message)?;
        line.push('\n');
        let mut input = child.stdin.take().ok_or_else(Self::invalid)?;
        input.write_all(line.as_bytes())
    }

    pub(super) fn parent_closed(timeout: i32) -> io::Result<bool> {
        let mut descriptor = libc::pollfd {
            fd: 0,
            events: libc::POLLIN,
            revents: 0,
        };
        let ready = unsafe { libc::poll(&mut descriptor, 1, timeout) };
        if ready < 0 {
            return Err(io::Error::last_os_error());
        }
        if ready == 0 {
            return Ok(false);
        }
        if descriptor.revents & libc::POLLNVAL != 0 {
            return Err(Self::invalid());
        }
        let mut byte = 0u8;
        let count = unsafe { libc::read(0, (&mut byte as *mut u8).cast(), 1) };
        if count < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(count == 0)
        }
    }

    pub(super) fn observe(child: &mut Child) -> io::Result<Option<ExitStatus>> {
        loop {
            if let Some(status) = child.try_wait()? {
                return Ok(Some(status));
            }
            if Self::parent_closed(100)? {
                return Ok(None);
            }
        }
    }
}

impl DispatchGuardian {
    pub(super) fn stop(child: &mut Child) -> io::Result<ExitStatus> {
        let pid = libc::pid_t::try_from(child.id()).map_err(|_| Self::invalid())?;
        let signal = |kind| {
            if unsafe { libc::killpg(pid, kind) } == 0 {
                return Ok(());
            }
            let error = io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ESRCH) {
                Ok(())
            } else {
                Err(error)
            }
        };
        let term = signal(libc::SIGTERM);
        let deadline = Instant::now() + Duration::from_millis(500);
        let waited = (|| loop {
            match child.try_wait() {
                Ok(Some(status)) => return Ok(Some(status)),
                Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(10)),
                Ok(None) => return Ok(None),
                Err(error) => return Err(error),
            }
        })();
        // Always signal the owned group, including descendants whose leader
        // has exited. Child ownership is never inferred from a persisted PID.
        let kill = signal(libc::SIGKILL);
        let reaped = child.wait();
        term?;
        waited?;
        kill?;
        reaped
    }

    pub(super) fn exit_code(status: ExitStatus) -> i32 {
        status
            .code()
            .unwrap_or_else(|| 128 + status.signal().unwrap_or(1))
    }

    pub(super) fn descriptors() -> io::Result<Vec<libc::c_int>> {
        #[cfg(target_os = "macos")]
        let directory = "/dev/fd";
        #[cfg(target_os = "linux")]
        let directory = "/proc/self/fd";
        let inventory = fs::read_dir(directory)?
            .map(|entry| {
                let entry = entry?;
                Ok(entry
                    .file_name()
                    .to_str()
                    .and_then(|name| name.parse::<libc::c_int>().ok()))
            })
            .collect::<io::Result<Vec<_>>>()?;
        let mut live = Vec::new();
        for fd in inventory.into_iter().flatten().filter(|fd| *fd >= 3) {
            loop {
                if unsafe { libc::fcntl(fd, libc::F_GETFD) } >= 0 {
                    live.push(fd);
                    break;
                }
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                if error.raw_os_error() != Some(libc::EBADF) {
                    return Err(error);
                }
                break;
            }
        }
        live.sort_unstable();
        live.dedup();
        Ok(live)
    }
}

#[cfg(test)]
#[path = "process_tests.rs"]
mod tests;
