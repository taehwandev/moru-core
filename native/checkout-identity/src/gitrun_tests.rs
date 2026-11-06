use super::*;
#[test]
fn raw_capture_preserves_filenames_and_undecodable_stderr() {
    let (stdout, stderr, success) = capture_raw(
        Command::new("/bin/sh").args(["-c", "printf 'a\\r\\nb\\000'; printf '\\377' >&2"]),
        Duration::from_secs(2),
    )
    .unwrap()
    .unwrap();
    assert_eq!(stdout, b"a\r\nb\0");
    assert_eq!(stderr, vec![255]);
    assert!(success);
}
#[test]
fn existing_text_contract_keeps_translation_and_stderr_validation() {
    assert_eq!(
        capture(Command::new("/bin/sh").args(["-c", "printf 'a\\r\\nb\\r'"])),
        Ok(Some("a\nb\n".into()))
    );
    assert_eq!(
        capture(Command::new("/bin/sh").args(["-c", "printf '\\377' >&2"])),
        Err(())
    );
    assert_eq!(
        capture(Command::new("/bin/sh").args(["-c", "exit 7"])),
        Ok(None)
    );
}
