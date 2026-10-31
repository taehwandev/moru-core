//! Failure propagation is part of the public process/library contract.

use moru_checkout_identity::CheckoutIdentity;
use std::io::{self, BufRead, Cursor, Read, Write};

struct Unreadable;

impl Read for Unreadable {
    fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::other("read failed"))
    }
}

impl BufRead for Unreadable {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        Err(io::Error::other("read failed"))
    }

    fn consume(&mut self, _: usize) {}
}

struct Unwritable {
    fail_flush: bool,
}

impl Write for Unwritable {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if self.fail_flush {
            Ok(bytes.len())
        } else {
            Err(io::Error::new(io::ErrorKind::BrokenPipe, "write failed"))
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        Err(io::Error::other("flush failed"))
    }
}

#[test]
fn reader_error_is_not_successful_eof() {
    assert!(CheckoutIdentity::serve(Unreadable, Vec::new()).is_err());
}

#[test]
fn broken_output_is_an_error() {
    assert!(
        CheckoutIdentity::serve(Cursor::new(b"{}\n"), Unwritable { fail_flush: false }).is_err()
    );
}

#[test]
fn failed_flush_is_an_error() {
    assert!(
        CheckoutIdentity::serve(Cursor::new(b"{}\n"), Unwritable { fail_flush: true }).is_err()
    );
}

#[test]
fn clean_empty_eof_is_silent_success() {
    let mut out = Vec::new();
    CheckoutIdentity::serve(Cursor::new(b""), &mut out).unwrap();
    assert!(out.is_empty());
}
