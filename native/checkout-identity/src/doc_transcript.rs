//! owner: DocTranscript; allowed imports: PythonJson, std, libc;
//! forbidden imports: process/providers, writes/state/markers; callers/tests:
//! DocTranscriptProcess, doc_transcript_tests; verification: streamed Python parity.
use crate::python_json::{ParseOutcome, PythonJson, Value};
use std::{
    collections::VecDeque,
    ffi::CString,
    fs::{self, File, Metadata},
    io::{self, BufRead, BufReader, Read, Seek, SeekFrom},
    os::unix::{
        ffi::OsStrExt,
        fs::MetadataExt,
        io::{AsRawFd, FromRawFd},
    },
    path::{Component, Path, PathBuf},
};

pub(crate) struct DocTranscript;
impl DocTranscript {
    pub(crate) fn compacted(path: &Path) -> Option<bool> {
        let (size, metadata) = Self::size(path);
        if size == 0 {
            return Some(false);
        }
        Self::scan(Self::open(path, &metadata?)?.ok()?, 0, false)
    }

    pub(crate) fn aligned(path: &Path, fallback: i64) -> Option<u64> {
        let (size, metadata) = Self::size(path);
        if size == 0 {
            return Some(0);
        }
        // Directory anchoring can need read permission where Python only needs
        // search permission. Only actual opened-file errors may return size.
        let mut file = Self::open(path, &metadata?)?.ok()?;
        let start = size.saturating_sub(65536);
        let tail = (|| -> io::Result<Option<Vec<u8>>> {
            file.seek(SeekFrom::Start(size - 1))?;
            let mut byte = [0];
            if file.read(&mut byte)? == 1 && byte[0] == b'\n' {
                return Ok(None);
            }
            file.seek(SeekFrom::Start(start))?;
            let mut tail = Vec::new();
            file.take(size - start).read_to_end(&mut tail)?;
            Ok(Some(tail))
        })();
        let tail = match tail {
            Ok(Some(tail)) => tail,
            Ok(None) | Err(_) => return Some(size),
        };
        if let Some(newline) = tail.iter().rposition(|byte| *byte == b'\n') {
            return Some(start + newline as u64 + 1);
        }
        Some(if fallback >= 0 && fallback as u64 <= start {
            fallback as u64
        } else {
            0
        })
    }

    pub(crate) fn due(path: &Path, offset: i64, redeliveries: i64, limit: i64) -> Option<bool> {
        // Preserve this ordering: exhausted/same-size inputs never open even a FIFO.
        if redeliveries >= limit {
            return Some(false);
        }
        let (size, metadata) = Self::size(path);
        if offset >= 0 && size == offset as u64 {
            return Some(false);
        }
        let offset = u64::try_from(offset).ok()?;
        let offset = if size < offset { 0 } else { offset };
        Self::scan(Self::open(path, &metadata?)?.ok()?, offset, true)
    }

    fn size(path: &Path) -> (u64, Option<Metadata>) {
        match fs::metadata(path) {
            Ok(metadata) if metadata.is_file() => (metadata.len(), Some(metadata)),
            _ => (0, None),
        }
    }

    fn open(path: &Path, expected: &Metadata) -> Option<io::Result<File>> {
        // Resolve ordinary links, then anchor each component to an owned directory
        // descriptor. NOFOLLOW avoids redirected ancestors; NONBLOCK prevents a
        // replacement FIFO from stalling before fstat can reject nonregular input.
        let resolved = match Self::resolve(path)? {
            Ok(resolved) => resolved,
            Err(error) => return Some(Err(error)),
        };
        let opened = (|| -> io::Result<File> {
            let mut file = File::open("/")?;
            let mut parts = resolved.components().peekable();
            while let Some(part) = parts.next() {
                let Component::Normal(name) = part else {
                    continue;
                };
                let name = CString::new(name.as_bytes())
                    .map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
                let flags = libc::O_RDONLY
                    | libc::O_CLOEXEC
                    | libc::O_NOFOLLOW
                    | libc::O_NONBLOCK
                    | libc::O_NOCTTY
                    | if parts.peek().is_some() {
                        libc::O_DIRECTORY
                    } else {
                        0
                    };
                let fd = unsafe { libc::openat(file.as_raw_fd(), name.as_ptr(), flags) };
                if fd < 0 {
                    return Err(io::Error::last_os_error());
                }
                file = unsafe { File::from_raw_fd(fd) };
            }
            Ok(file)
        })();
        let file = match opened {
            Ok(file) => file,
            Err(error) => return Some(Err(error)),
        };
        for actual in [file.metadata().ok()?, fs::metadata(path).ok()?] {
            if !actual.is_file() || actual.dev() != expected.dev() || actual.ino() != expected.ino()
            {
                return None;
            }
        }
        Some(Ok(file))
    }

    fn resolve(path: &Path) -> Option<io::Result<PathBuf>> {
        let absolute = if path.is_absolute() {
            path.to_owned()
        } else {
            match std::env::current_dir() {
                Ok(cwd) => cwd.join(path),
                Err(error) => return Some(Err(error)),
            }
        };
        let mut parts: VecDeque<_> = absolute
            .components()
            .map(|p| p.as_os_str().to_owned())
            .collect();
        let mut resolved = PathBuf::new();
        let mut links = 0;
        while let Some(part) = parts.pop_front() {
            match Path::new(&part).components().next()? {
                Component::RootDir => resolved = PathBuf::from("/"),
                Component::CurDir => {}
                Component::ParentDir => {
                    resolved.pop();
                }
                Component::Normal(name) => {
                    let next = resolved.join(name);
                    if Self::descriptor(&next) {
                        return None;
                    }
                    match fs::symlink_metadata(&next) {
                        Ok(metadata) if metadata.is_symlink() => {
                            links += 1;
                            if links > 40 {
                                return None;
                            }
                            let target = match fs::read_link(&next) {
                                Ok(target) => target,
                                Err(error) => return Some(Err(error)),
                            };
                            for part in target.components().rev() {
                                parts.push_front(part.as_os_str().to_owned());
                            }
                        }
                        Ok(_) => resolved = next,
                        Err(error) => return Some(Err(error)),
                    }
                }
                _ => return None,
            }
        }
        Some(Ok(resolved))
    }

    fn descriptor(path: &Path) -> bool {
        let Some(text) = path.to_str() else {
            return false;
        };
        let text = if cfg!(target_os = "macos") {
            text.to_ascii_lowercase()
        } else {
            text.to_owned()
        };
        let parts: Vec<_> = text.split('/').filter(|part| !part.is_empty()).collect();
        (parts.first() == Some(&"dev")
            && matches!(parts.get(1), Some(&"fd" | &"stdin" | &"stdout" | &"stderr")))
            || (parts.first() == Some(&"proc")
                && (parts.get(2) == Some(&"fd")
                    || (parts.get(2) == Some(&"task") && parts.get(4) == Some(&"fd"))))
    }

    fn scan(mut file: File, offset: u64, complete: bool) -> Option<bool> {
        file.seek(SeekFrom::Start(offset)).ok()?;
        let mut reader = BufReader::new(file);
        let mut line = Vec::new();
        // Read to actual EOF, including concurrent appends; metadata was only an
        // equality/rewrite hint. There is no total-size or per-line cutoff.
        loop {
            line.clear();
            if reader.read_until(b'\n', &mut line).ok()? == 0 {
                return Some(false);
            }
            if complete && !line.ends_with(b"\n") {
                continue;
            }
            if ![
                b"\"compact_boundary\"".as_slice(),
                b"\"compacted\"",
                b"\"CHECKPOINT\"",
            ]
            .iter()
            .any(|mark| line.windows(mark.len()).any(|window| window == *mark))
            {
                continue;
            }
            if Self::boundary(&line)? {
                return Some(true);
            }
        }
    }

    fn boundary(bytes: &[u8]) -> Option<bool> {
        // json.loads(bytes) detects UTF-16/32 as well as a UTF-8 BOM. Such input
        // cannot be handed to our UTF-8 parser as a merely invalid JSON row.
        if bytes.starts_with(b"\xff\xfe")
            || bytes.starts_with(b"\xfe\xff")
            || bytes.starts_with(b"\0\0\xfe\xff")
            || (bytes.len() >= 4 && (bytes[0] == 0 || bytes[1] == 0))
        {
            return None;
        }
        let bytes = bytes.strip_prefix(b"\xef\xbb\xbf").unwrap_or(bytes);
        let text = match std::str::from_utf8(bytes) {
            Ok(text) => text,
            Err(error) => {
                // json.loads(bytes) decodes with surrogatepass. Canonical raw
                // UTF-8 surrogate triples are source-valid, but not Rust strings.
                return if matches!(
                    &bytes[error.valid_up_to()..],
                    [0xed, 0xa0..=0xbf, 0x80..=0xbf, ..]
                ) {
                    None
                } else {
                    Some(false)
                };
            }
        };
        let row = match PythonJson::parse_outcome(text) {
            ParseOutcome::Value(value) => value,
            ParseOutcome::Invalid => return Some(false),
            ParseOutcome::Unsupported => return None,
        };
        Some(Self::is_compaction(&row))
    }

    fn is_compaction(row: &Value) -> bool {
        let kind = row.get("type").and_then(Value::as_str);
        kind == Some("compacted")
            || (kind == Some("system")
                && row.get("subtype").and_then(Value::as_str) == Some("compact_boundary"))
            || (kind == Some("CHECKPOINT")
                && row
                    .get("content")
                    .and_then(Value::as_str)
                    .is_some_and(|text| text.starts_with("# Resuming from a compaction")))
    }
}

#[cfg(test)]
#[path = "doc_transcript_tests.rs"]
mod tests;
