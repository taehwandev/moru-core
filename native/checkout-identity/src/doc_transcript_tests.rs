use super::DocTranscript;
use std::{
    ffi::CString,
    fs::{self, File},
    io::{Seek, SeekFrom},
    os::unix::{fs::symlink, io::AsRawFd, net::UnixListener},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

const BOUNDARY: &[u8] = b"{\"type\":\"compacted\"}\n";
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "moru-doc-transcript-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        Self(root.canonicalize().unwrap())
    }
    fn write(&self, bytes: &[u8]) -> PathBuf {
        let path = self.0.join("transcript.jsonl");
        fs::write(&path, bytes).unwrap();
        path
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn all_three_boundaries_preserve_exact_shapes() {
    let fixture = Fixture::new();
    for row in [
        r#"{"type":"compacted"}"#,
        r#"{"type": "system", "subtype": "compact_boundary"}"#,
        r##"{"type":"CHECKPOINT","content":"# Resuming from a compaction\nsummary"}"##,
    ] {
        let path = fixture.write(format!("{row}\n").as_bytes());
        assert_eq!(DocTranscript::compacted(&path), Some(true));
        assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(true));
    }
    for row in [
        "null",
        "[]",
        "true",
        r#""compacted""#,
        r#"{"type":["compacted"]}"#,
        r#"{"type":"SYSTEM","subtype":"compact_boundary"}"#,
        r#"{"type":"CHECKPOINT","content":null}"#,
        r##"{"type":"CHECKPOINT","content":["# Resuming from a compaction"]}"##,
        r##"{"type":"CHECKPOINT","content":" # Resuming from a compaction"}"##,
    ] {
        let path = fixture.write(format!("{row}\n").as_bytes());
        assert_eq!(DocTranscript::compacted(&path), Some(false), "{row}");
    }
}

#[test]
fn unterminated_rows_are_only_eligible_for_compacted() {
    let fixture = Fixture::new();
    let path = fixture.write(&BOUNDARY[..BOUNDARY.len() - 1]);
    assert_eq!(DocTranscript::compacted(&path), Some(true));
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(false));
    assert_eq!(DocTranscript::aligned(&path, 1), Some(0));
    fixture.write(BOUNDARY);
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(true));
    assert_eq!(
        DocTranscript::aligned(&path, 0),
        Some(BOUNDARY.len() as u64)
    );
}

#[test]
fn offset_equality_rewrites_and_exhaustion_short_circuit() {
    let fixture = Fixture::new();
    let path = fixture.write(BOUNDARY);
    assert_eq!(
        DocTranscript::due(&path, BOUNDARY.len() as i64, 0, 2),
        Some(false)
    );
    assert_eq!(DocTranscript::due(&path, 1, 0, 2), Some(false));
    assert_eq!(DocTranscript::due(&path, 999, 0, 2), Some(true));
    assert_eq!(DocTranscript::due(&path, -1, 0, 2), None);
    assert_eq!(DocTranscript::due(&path, -1, 2, 2), Some(false));
    assert_eq!(DocTranscript::due(&path, 0, -2, -1), Some(true));
    let mut bytes = b"null\n".to_vec();
    bytes.extend_from_slice(BOUNDARY);
    fixture.write(&bytes);
    assert_eq!(DocTranscript::due(&path, 5, 0, 2), Some(true));
    assert_eq!(DocTranscript::due(&path, 6, 0, 2), Some(false));
}

#[test]
fn missing_empty_and_directory_match_source_size_shortcuts() {
    let fixture = Fixture::new();
    for path in [
        fixture.0.join("missing"),
        fixture.0.clone(),
        fixture.write(b""),
    ] {
        assert_eq!(DocTranscript::compacted(&path), Some(false));
        assert_eq!(DocTranscript::aligned(&path, 999), Some(0));
        assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(false));
        assert_eq!(DocTranscript::due(&path, 99, 2, 2), Some(false));
    }
    assert_eq!(
        DocTranscript::due(&fixture.0.join("missing"), 1, 0, 2),
        None
    );
    assert_eq!(DocTranscript::due(&fixture.0, 1, 0, 2), None);
    assert_eq!(
        DocTranscript::due(&fixture.0.join("transcript.jsonl"), 1, 0, 2),
        Some(false)
    );
}

#[test]
fn alignment_uses_only_last_64k_and_bounded_fallback() {
    let fixture = Fixture::new();
    let mut bytes = b"x\n".to_vec();
    bytes.resize(70002, b'x');
    let path = fixture.write(&bytes);
    let start = bytes.len() as i64 - 65536;
    for (fallback, expected) in [
        (-1, 0),
        (0, 0),
        (2, 2),
        (start, start as u64),
        (start + 1, 0),
    ] {
        assert_eq!(DocTranscript::aligned(&path, fallback), Some(expected));
    }
    bytes[start as usize] = b'\n';
    fixture.write(&bytes);
    assert_eq!(DocTranscript::aligned(&path, 2), Some(start as u64 + 1));
    let last = bytes.len() - 1;
    bytes[last] = b'\n';
    fixture.write(&bytes);
    assert_eq!(DocTranscript::aligned(&path, -9), Some(bytes.len() as u64));
}

#[test]
fn search_only_ancestor_does_not_advance_past_an_unterminated_row() {
    use std::os::unix::fs::PermissionsExt;
    let fixture = Fixture::new();
    let directory = fixture.0.join("search-only");
    fs::create_dir(&directory).unwrap();
    let path = directory.join("transcript");
    fs::write(&path, b"partial").unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o111)).unwrap();
    // Traversing an ancestor requires search, not directory read permission.
    let source_read = fs::read(&path);
    let anchor_open = File::open(&directory);
    let aligned = DocTranscript::aligned(&path, 0);
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
    assert_eq!(source_read.unwrap(), b"partial");
    match anchor_open {
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
            assert_eq!(aligned, None);
        }
        Ok(_) => assert_eq!(aligned, Some(0)), // root/capability/ACL permits anchoring.
        Err(error) => panic!("unexpected directory open failure: {error}"),
    }
}

#[test]
fn malformed_rows_duplicates_and_nonfinite_numbers_match_python() {
    let fixture = Fixture::new();
    let path =
        fixture.write(b"{\"type\":\"compacted\",}\n{\"type\":\"compacted\",\"type\":\"other\"}\n");
    assert_eq!(DocTranscript::compacted(&path), Some(false));
    fixture.write(
        b"{\"type\":\"other\",\"type\":\"compacted\",\"n\":NaN,\"x\":Infinity,\"y\":-Infinity}\n",
    );
    assert_eq!(DocTranscript::compacted(&path), Some(true));
    fixture.write(b"{\"type\":\"compacted\",\"bad\":\"\xff\"}\n");
    assert_eq!(DocTranscript::compacted(&path), Some(false));
    fixture.write(b"{\"type\":\"compacted\",\"bad\":\"\\ud800\"}\n");
    assert_eq!(DocTranscript::compacted(&path), None);
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), None);
    assert_eq!(
        DocTranscript::due(&path, fs::metadata(&path).unwrap().len() as i64, 0, 2),
        Some(false)
    );
    let nested = format!(
        "{{\"type\":\"compacted\",\"unused\":{}null{}}}\n",
        "[".repeat(140),
        "]".repeat(140)
    );
    fixture.write(nested.as_bytes());
    assert_eq!(DocTranscript::compacted(&path), None);
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), None);
}

#[test]
fn cheap_filter_has_quoted_markers_and_ignores_unused_unsupported_rows() {
    let fixture = Fixture::new();
    let path = fixture.write(b"{\"type\":\"comp\\u0061cted\"}\n{\"bad\":\"\\ud800\"}\n");
    assert_eq!(DocTranscript::compacted(&path), Some(false));
    fixture.write(b"{\"type\":\"comp\\u0061cted\",\"other\":\"compacted\"}\n");
    assert_eq!(DocTranscript::compacted(&path), Some(true));
}

#[test]
fn raw_surrogatepass_triples_decline_but_invalid_utf8_is_skipped() {
    let fixture = Fixture::new();
    for raw in [b"\xed\xa0\x80".as_slice(), b"\xed\xbf\xbf"] {
        let mut bytes = b"{\"type\":\"compacted\",\"unused\":\"".to_vec();
        bytes.extend_from_slice(raw);
        bytes.extend_from_slice(b"\"}\n");
        let path = fixture.write(&bytes);
        assert_eq!(DocTranscript::compacted(&path), None);
        assert_eq!(DocTranscript::due(&path, 0, 0, 2), None);
    }
    for raw in [
        b"\xff".as_slice(),
        b"\xed\xa0",
        b"\xed\xa0\xff",
        b"\xed\x9f\xff",
    ] {
        let mut bytes = b"{\"type\":\"compacted\",\"unused\":\"".to_vec();
        bytes.extend_from_slice(raw);
        bytes.extend_from_slice(b"\"}\n");
        let path = fixture.write(&bytes);
        assert_eq!(DocTranscript::compacted(&path), Some(false));
        assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(false));
    }
}

#[test]
fn utf8_bom_is_accepted_and_alternative_encoding_candidates_decline() {
    let fixture = Fixture::new();
    let mut bytes = b"\xef\xbb\xbf".to_vec();
    bytes.extend_from_slice(BOUNDARY);
    let path = fixture.write(&bytes);
    assert_eq!(DocTranscript::compacted(&path), Some(true));
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(true));
    // Valid UTF-16BE JSON: unrelated Unicode content encodes raw ASCII marker
    // bytes. Its ASCII-looking bytes are still UTF-8 valid, so detect the NULs.
    let marker = b"\"compacted\"x";
    let content: String = marker
        .chunks_exact(2)
        .map(|pair| char::from_u32(u16::from_be_bytes([pair[0], pair[1]]) as u32).unwrap())
        .collect();
    let json = format!("{{\"type\":\"compacted\",\"content\":\"{content}\"}}\n");
    let bytes: Vec<u8> = json.encode_utf16().flat_map(u16::to_be_bytes).collect();
    assert!(bytes
        .windows(b"\"compacted\"".len())
        .any(|w| w == b"\"compacted\""));
    fixture.write(&bytes);
    assert_eq!(DocTranscript::compacted(&path), None);
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), None);
    for prefix in [
        b"\xff\xfe".as_slice(),
        b"\xfe\xff",
        b"\0\0\xfe\xff",
        b"x\0xx",
    ] {
        let mut bytes = prefix.to_vec();
        bytes.extend_from_slice(BOUNDARY);
        fixture.write(&bytes);
        assert_eq!(DocTranscript::compacted(&path), None);
    }
}

#[test]
fn long_rows_stream_without_a_line_cap_and_leave_owned_files_unchanged() {
    let fixture = Fixture::new();
    let mut bytes = vec![b' '; 1024 * 1024];
    bytes.extend_from_slice(BOUNDARY);
    let path = fixture.write(&bytes);
    let before = fs::metadata(&path).unwrap().modified().unwrap();
    assert_eq!(DocTranscript::compacted(&path), Some(true));
    assert_eq!(DocTranscript::due(&path, 0, 0, 2), Some(true));
    assert_eq!(DocTranscript::aligned(&path, 0), Some(bytes.len() as u64));
    assert_eq!(fs::read(&path).unwrap(), bytes);
    assert_eq!(fs::metadata(&path).unwrap().modified().unwrap(), before);
    assert_eq!(fs::read_dir(&fixture.0).unwrap().count(), 1);
}

#[test]
fn scanning_reaches_appends_beyond_the_initial_metadata_size() {
    use std::io::Write;
    let fixture = Fixture::new();
    let path = fixture.write(b"null\n");
    let (_, metadata) = DocTranscript::size(&path);
    let file = DocTranscript::open(&path, &metadata.unwrap())
        .unwrap()
        .unwrap();
    let mut append = fs::OpenOptions::new().append(true).open(&path).unwrap();
    append.write_all(BOUNDARY).unwrap();
    drop(append);
    assert_eq!(DocTranscript::scan(file, 0, true), Some(true));
}

#[test]
fn ordinary_relative_and_directory_symlinks_are_supported() {
    let fixture = Fixture::new();
    let path = fixture.write(BOUNDARY);
    symlink("transcript.jsonl", fixture.0.join("relative")).unwrap();
    symlink(&fixture.0, fixture.0.join("directory")).unwrap();
    for alias in [
        fixture.0.join("relative"),
        fixture.0.join("directory/transcript.jsonl"),
    ] {
        assert_eq!(DocTranscript::compacted(&alias), Some(true));
        assert_eq!(
            DocTranscript::aligned(&alias, 0),
            Some(BOUNDARY.len() as u64)
        );
        assert_eq!(DocTranscript::due(&alias, 0, 0, 2), Some(true));
    }
    let metadata = fs::metadata(&path).unwrap();
    let _held = File::open(&path).unwrap();
    fs::remove_file(&path).unwrap();
    fixture.write(b"replacement\n");
    assert!(DocTranscript::open(&path, &metadata).is_none());
}

#[test]
fn nonregular_sources_are_not_consumed_or_blocked() {
    let fixture = Fixture::new();
    let fifo = fixture.0.join("fifo");
    let name = CString::new(fifo.to_str().unwrap()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    let socket = fixture.0.join("socket");
    let _listener = UnixListener::bind(&socket).unwrap();
    for path in [&fifo, &socket, Path::new("/dev/null")] {
        assert_eq!(DocTranscript::compacted(path), Some(false));
        assert_eq!(DocTranscript::aligned(path, 9), Some(0));
        assert_eq!(DocTranscript::due(path, 0, 0, 2), Some(false));
        assert_eq!(DocTranscript::due(path, 1, 0, 2), None);
    }
}

#[test]
fn fd_namespace_and_symlink_aliases_decline_without_moving_shared_offset() {
    let fixture = Fixture::new();
    let path = fixture.write(BOUNDARY);
    let mut file = File::open(&path).unwrap();
    file.seek(SeekFrom::Start(3)).unwrap();
    let alias = PathBuf::from(format!("/dev/fd/{}", file.as_raw_fd()));
    symlink(&alias, fixture.0.join("indirect")).unwrap();
    let mut paths = vec![alias, fixture.0.join("indirect")];
    if cfg!(target_os = "linux") {
        paths.push(PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd())));
        paths.push(PathBuf::from(format!(
            "/proc/{}/fd/{}",
            std::process::id(),
            file.as_raw_fd()
        )));
    }
    for alias in paths {
        assert_eq!(
            DocTranscript::compacted(&alias),
            None,
            "{}",
            alias.display()
        );
        assert_eq!(DocTranscript::aligned(&alias, 0), None);
        assert_eq!(DocTranscript::due(&alias, 1, 0, 2), None);
        assert_eq!(file.stream_position().unwrap(), 3);
    }
}
