//! Bounded NDJSON framing, including oversize drain and recovery.

use std::io::{self, BufRead};

pub(crate) enum Frame {
    Eof,
    Line,
    TooLarge,
}

impl Frame {
    pub(crate) const MAX_LINE: usize = 1_048_576;

    pub(crate) fn read<R: BufRead>(reader: &mut R, buf: &mut Vec<u8>) -> io::Result<Self> {
        buf.clear();
        let mut total = 0usize;
        let mut seen = false;
        loop {
            let chunk = match reader.fill_buf() {
                Ok(chunk) => chunk,
                Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
                Err(err) => return Err(err),
            };
            if chunk.is_empty() {
                break;
            }
            let (take, done) = match chunk.iter().position(|&b| b == b'\n') {
                Some(pos) => (pos + 1, true),
                None => (chunk.len(), false),
            };
            seen = true;
            total = total.saturating_add(take);
            if total <= Self::MAX_LINE {
                buf.extend_from_slice(&chunk[..take]);
            }
            reader.consume(take);
            if done {
                break;
            }
        }
        if !seen {
            Ok(Self::Eof)
        } else if total > Self::MAX_LINE {
            buf.clear();
            Ok(Self::TooLarge)
        } else {
            Ok(Self::Line)
        }
    }
}
