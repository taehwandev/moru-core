//! owner: bounded snapshot of a regular descriptor admitted by the review caller.
//! allowed imports: positional reads, UTF-8 classification and SHA-256.
//! forbidden imports: pathname opens, Git, provider calls and authority decisions.
//! callers/tests: review packet probe; native snapshot and packet parity fixtures.
//! verification: offset preservation, original bytes, size cap and binary/BOM handling.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{self, ErrorKind},
    os::{fd::AsFd, unix::fs::FileExt},
};

const MAX_SOURCE_BYTES: usize = 256 * 1024;

pub(crate) struct ReviewPacketSnapshot;

impl ReviewPacketSnapshot {
    pub(crate) fn read_stdin() -> Option<Value> {
        let file = File::from(io::stdin().as_fd().try_clone_to_owned().ok()?);
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut data = Vec::new();
        let mut chunk = [0; 16 * 1024];
        while data.len() <= MAX_SOURCE_BYTES {
            let limit = (MAX_SOURCE_BYTES + 1 - data.len()).min(chunk.len());
            match file.read_at(&mut chunk[..limit], data.len() as u64) {
                Ok(0) => break,
                Ok(count) => data.extend_from_slice(&chunk[..count]),
                Err(error) if error.kind() == ErrorKind::Interrupted => continue,
                Err(_) => return None,
            }
        }
        if data.len() > MAX_SOURCE_BYTES {
            return Some(json!({"kind": "oversize"}));
        }
        let digest = format!("{:x}", Sha256::digest(&data));
        if let Ok(text) = std::str::from_utf8(&data) {
            if !data.contains(&0) {
                return Some(json!({"kind": "text", "data": text, "sha256": digest}));
            }
        }
        Some(json!({"kind": "binary", "data": hexadecimal(&data), "sha256": digest}))
    }
}

fn hexadecimal(data: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(2 * data.len());
    for byte in data {
        text.push(char::from(HEX[(byte >> 4) as usize]));
        text.push(char::from(HEX[(byte & 15) as usize]));
    }
    text
}
