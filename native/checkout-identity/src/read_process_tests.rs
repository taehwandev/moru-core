use super::*;

#[test]
fn capture_preserves_both_pipes_exit_status_and_null_stdin() {
    let (stdout, stderr, success) = capture_raw(
        Command::new("/bin/sh").stdin(Stdio::null()).args([
            "-c",
            "read value; printf 'a\\r\\n\\000'; printf '\\377' >&2; exit 9",
        ]),
        Duration::from_secs(1),
    )
    .unwrap()
    .unwrap();
    assert_eq!(stdout, b"a\r\n\0");
    assert_eq!(stderr, [255]);
    assert!(!success);
}

#[test]
fn absent_executable_and_busy_child_respect_deadline() {
    assert!(capture_raw(
        &mut Command::new("/dev/null/not-an-executable"),
        Duration::from_secs(1)
    )
    .unwrap()
    .is_none());
    let started = Instant::now();
    assert!(capture_raw(
        Command::new("/bin/sh").args(["-c", "while :; do :; done"]),
        Duration::from_millis(30)
    )
    .unwrap()
    .is_none());
    assert!(started.elapsed() < Duration::from_secs(2));
}

#[test]
fn exited_child_with_inherited_pipe_stays_bounded() {
    let started = Instant::now();
    assert!(capture_raw(
        Command::new("/bin/sh").args(["-c", "/bin/sleep 0.2 & exit 0"]),
        Duration::from_millis(30)
    )
    .unwrap()
    .is_none());
    assert!(started.elapsed() < Duration::from_secs(2));
}
