//! One owner for missing, invalid and decoded Git metadata text.

use crate::text::Text;
use std::{fs, io::ErrorKind};

pub(crate) enum MetadataText {
    Missing,
    Bad,
    Text(String),
}

impl MetadataText {
    pub(crate) fn load(path: &str) -> Self {
        match fs::read(path) {
            Ok(data) => match String::from_utf8(data) {
                Ok(text) => Self::Text(Text::universal_newlines(&text)),
                Err(_) => Self::Bad,
            },
            Err(e) if e.kind() == ErrorKind::NotFound => Self::Missing,
            Err(_) => Self::Bad,
        }
    }
}
