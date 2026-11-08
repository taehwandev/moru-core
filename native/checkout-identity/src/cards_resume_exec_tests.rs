use super::CardResumeExec;
use std::{ffi::OsStr, os::unix::ffi::OsStrExt};

#[test]
fn path_candidates_preserve_empty_relative_repeated_slash_and_raw_byte_components() {
    let candidates =
        CardResumeExec::candidates(OsStr::from_bytes(b":relative:/absolute/:double//:raw\xff:"))
            .unwrap();
    let actual: Vec<_> = candidates.iter().map(|value| value.as_bytes()).collect();
    assert_eq!(
        actual,
        vec![
            b"codex".as_slice(),
            b"relative/codex",
            b"/absolute/codex",
            b"double//codex",
            b"raw\xff/codex",
            b"codex"
        ]
    );
    assert_eq!(
        CardResumeExec::candidates(OsStr::new("")).unwrap()[0].as_bytes(),
        b"codex"
    );
}

#[test]
fn invalid_path_nul_is_refused_before_any_fork() {
    let error = CardResumeExec::candidates(OsStr::from_bytes(b"part\0invalid")).unwrap_err();
    assert_eq!(error.raw_os_error(), Some(libc::EINVAL));
}

#[test]
fn absent_fd_directory_falls_back_to_live_descriptor_scan_without_changing_flags() {
    use std::{
        fs,
        os::{
            fd::{AsRawFd, FromRawFd, OwnedFd},
            unix::net::UnixStream,
        },
    };
    let (reader, _writer) = UnixStream::pair().unwrap();
    let fd = reader.as_raw_fd();
    let duplicate = unsafe { libc::dup(fd) };
    assert!(duplicate >= 3);
    let duplicate = unsafe { OwnedFd::from_raw_fd(duplicate) };
    let original_flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    let duplicate_flags = unsafe { libc::fcntl(duplicate.as_raw_fd(), libc::F_GETFD) };
    assert_ne!(original_flags & libc::FD_CLOEXEC, 0);
    assert_eq!(duplicate_flags & libc::FD_CLOEXEC, 0);
    let root = std::env::temp_dir().join(format!("moru-no-fd-directory-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    let result = CardResumeExec::descriptors_from(&root.join("absent"));
    fs::remove_dir(&root).unwrap();
    let descriptors = result.unwrap();
    assert!(descriptors.contains(&fd));
    assert!(descriptors.contains(&duplicate.as_raw_fd()));
    assert!(descriptors.iter().all(|fd| *fd >= 3));
    assert_eq!(unsafe { libc::fcntl(fd, libc::F_GETFD) }, original_flags);
    assert_eq!(
        unsafe { libc::fcntl(duplicate.as_raw_fd(), libc::F_GETFD) },
        duplicate_flags
    );
}

#[test]
fn brute_force_limit_matches_sysconf_sentinel_and_keeps_the_full_representable_range() {
    assert_eq!(CardResumeExec::scan_limit(-1), 256);
    assert_eq!(CardResumeExec::scan_limit(4096), 4096);
    assert_eq!(CardResumeExec::scan_limit(0), 0);
    assert_eq!(
        CardResumeExec::scan_limit(libc::c_long::MAX),
        libc::c_int::MAX as libc::c_long + 1
    );
}
