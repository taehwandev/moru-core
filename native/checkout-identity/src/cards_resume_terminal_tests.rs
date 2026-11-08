use super::CardResumeTerminal;
use std::{
    io::{Read, Write},
    os::{fd::AsRawFd, unix::net::UnixStream},
};

fn eof_line(bytes: &[u8]) -> Option<Vec<u8>> {
    let (reader, mut writer) = UnixStream::pair().unwrap();
    writer.write_all(bytes).unwrap();
    drop(writer);
    CardResumeTerminal::fd_line(reader.as_raw_fd()).unwrap()
}

#[test]
fn terminal_line_trims_lf_then_cr_but_keeps_other_bytes_for_parent_validation() {
    assert_eq!(eof_line(b"1\n"), Some(b"1".to_vec()));
    assert_eq!(eof_line(b"1\r\n"), Some(b"1".to_vec()));
    assert_eq!(eof_line(b" \t1 \n"), Some(b" \t1 ".to_vec()));
    assert_eq!(eof_line(b"1\xff\n"), Some(b"1\xff".to_vec()));
    assert_eq!(eof_line(b"\n"), Some(vec![]));
    assert_eq!(eof_line(b""), None);
}

#[test]
fn partial_eof_drops_the_final_byte_unconditionally_then_optional_cr() {
    assert_eq!(eof_line(b"123"), Some(b"12".to_vec()));
    assert_eq!(eof_line(b"1"), Some(vec![]));
    assert_eq!(eof_line(b"12\r"), Some(b"12".to_vec()));
    assert_eq!(eof_line(b"1\r2"), Some(b"1".to_vec()));
}

#[test]
fn fgets_growth_boundaries_retain_every_complete_line_byte() {
    for length in [98, 99, 100, 198, 199, 200, 398, 399, 400, 1599, 3200] {
        let mut input = vec![b'1'; length];
        input.push(b'\n');
        assert_eq!(
            eof_line(&input),
            Some(vec![b'1'; length]),
            "length {length}"
        );
    }
    assert_eq!(CardResumeTerminal::increment(0).unwrap(), 100);
    assert_eq!(CardResumeTerminal::increment(99).unwrap(), 101);
    assert_eq!(CardResumeTerminal::increment(199).unwrap(), 201);
    assert_eq!(
        CardResumeTerminal::increment(libc::c_int::MAX as usize - 2).unwrap(),
        libc::c_int::MAX as usize
    );
    assert_eq!(
        CardResumeTerminal::increment(libc::c_int::MAX as usize - 1)
            .unwrap_err()
            .to_string(),
        "input line too long"
    );
}

#[test]
fn embedded_nul_uses_c_strlen_and_later_fgets_overwrites_the_truncated_suffix() {
    assert_eq!(eof_line(b"1\0junk\n\n"), Some(b"1".to_vec()));
    assert_eq!(eof_line(b"1\0junk\n"), Some(vec![]));
    assert_eq!(eof_line(b"12\0discard\n3\n"), Some(b"123".to_vec()));
}

#[test]
fn stdio_read_ahead_is_consumed_and_the_original_descriptor_stays_open_and_unchanged() {
    let (mut reader, mut writer) = UnixStream::pair().unwrap();
    writer.write_all(b"1\nprovider-input\n").unwrap();
    drop(writer);
    let fd = reader.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    assert_eq!(
        CardResumeTerminal::fd_line(fd).unwrap(),
        Some(b"1".to_vec())
    );
    assert_eq!(unsafe { libc::fcntl(fd, libc::F_GETFL) }, flags);
    let mut remaining = Vec::new();
    reader.read_to_end(&mut remaining).unwrap();
    assert!(
        remaining.is_empty(),
        "libc-buffered read-ahead must not return to the kernel queue"
    );
}

#[test]
fn non_eintr_errors_return_prior_successful_chunks_or_eof_without_toggling_nonblocking() {
    let (reader, mut writer) = UnixStream::pair().unwrap();
    reader.set_nonblocking(true).unwrap();
    let fd = reader.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
    assert_eq!(
        CardResumeTerminal::fd_line(fd).unwrap(),
        None,
        "EAGAIN without data becomes EOF"
    );
    writer.write_all(&[b'1'; 99]).unwrap();
    assert_eq!(
        CardResumeTerminal::fd_line(fd).unwrap(),
        Some(vec![b'1'; 98])
    );
    assert_eq!(unsafe { libc::fcntl(fd, libc::F_GETFL) }, flags);
}
