use super::*;
use std::{
    fs::{File, OpenOptions},
    os::fd::AsRawFd,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "moru-guardian-fd-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn descriptor_inventory_keeps_live_owned_fd_and_filters_stdio() {
    let f = Fixture::new();
    let file = File::create(f.0.join("fd")).unwrap();
    let descriptors = DispatchGuardian::descriptors().unwrap();
    assert!(descriptors.contains(&file.as_raw_fd()));
    assert!(descriptors.iter().all(|fd| *fd >= 3));
    assert!(descriptors.windows(2).all(|pair| pair[0] < pair[1]));
}

#[test]
fn gate_spawn_closes_inherited_flock_without_closing_new_exec_error_pipe() {
    let f = Fixture::new();
    let path = f.0.join("execution.lock");
    let file = File::create(&path).unwrap();
    let fd = file.as_raw_fd();
    assert_eq!(unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) }, 0);
    let mut command = Command::new("/bin/cat");
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    // Make this FD inheritable only in this child. Clearing CLOEXEC in the
    // multithreaded harness would leak the fixture into unrelated test children.
    unsafe {
        command.pre_exec(move || {
            if libc::fcntl(fd, libc::F_SETFD, 0) < 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(())
            }
        });
    }
    DispatchGuardian::isolate(&mut command, DispatchGuardian::descriptors().unwrap());
    let mut child = command.spawn().unwrap();
    assert_eq!(
        unsafe { libc::getpgid(child.id() as i32) },
        child.id() as i32
    );
    drop(file);
    let independent = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    let acquired = unsafe { libc::flock(independent.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    drop(child.stdin.take());
    DispatchGuardian::stop(&mut child).unwrap();
    assert_eq!(
        acquired, 0,
        "worker must not retain guardian's execution lock"
    );
    let mut missing = Command::new(f.0.join("missing"));
    DispatchGuardian::isolate(&mut missing, DispatchGuardian::descriptors().unwrap());
    assert_eq!(
        missing.spawn().unwrap_err().raw_os_error(),
        Some(libc::ENOENT)
    );
}

#[test]
fn owned_child_exit_is_preserved_and_term_resistant_group_is_killed_within_bound() {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", "exit 7"]);
    DispatchGuardian::isolate(&mut command, DispatchGuardian::descriptors().unwrap());
    let mut done = command.spawn().unwrap();
    let status = done.wait().unwrap();
    assert_eq!(DispatchGuardian::exit_code(status), 7);
    assert_eq!(
        DispatchGuardian::exit_code(DispatchGuardian::stop(&mut done).unwrap()),
        7
    );
    let mut command = Command::new("/bin/sh");
    command
        .args(["-c", "trap '' TERM; printf ready; exec /bin/cat"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    DispatchGuardian::isolate(&mut command, DispatchGuardian::descriptors().unwrap());
    let mut child = command.spawn().unwrap();
    use std::io::Read;
    let mut ready = [0; 5];
    child.stdout.take().unwrap().read_exact(&mut ready).unwrap();
    assert_eq!(&ready, b"ready");
    let started = Instant::now();
    let status = DispatchGuardian::stop(&mut child).unwrap();
    assert_eq!(DispatchGuardian::exit_code(status), 128 + libc::SIGKILL);
    assert!(started.elapsed() >= Duration::from_millis(500));
    assert!(started.elapsed() < Duration::from_secs(2));
}
