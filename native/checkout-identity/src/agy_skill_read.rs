//! owner: read-only AGY partial skill range notice;
//! allowed imports: bounded Python-compatible file reads and text helpers;
//! forbidden imports: advisory deduplication state, tool policy and writes;
//! callers/tests: durable AGY ingress, private probe and adapter parity;
//! verification: Python line boundaries, lexical names and exact range text.
use crate::{
    python_input_file::{FileRead, PythonInputFile},
    text::Text,
};
use std::{
    ffi::OsStr,
    path::{Component, Path},
};

pub(crate) struct AgySkillRead;

impl AgySkillRead {
    pub(crate) fn note(path: &str, start: i64, end: i64) -> Option<String> {
        let path = Path::new(path);
        if path.file_name()? != "SKILL.md" {
            return None;
        }
        let FileRead::Bytes(bytes) = PythonInputFile::read(path.as_os_str(), 512 * 1024, false)?
        else {
            return None;
        };
        let text = Text::universal_newlines(std::str::from_utf8(&bytes).ok()?);
        let total = i64::try_from(text.split_terminator(line_boundary).count()).ok()?;
        let first = if start == 0 { 1 } else { start };
        let last = if end == 0 { total } else { end };
        if first <= 1 && last >= total {
            return Some(String::new());
        }
        let parent = match path.parent()?.components().next_back() {
            Some(Component::Normal(name)) => name,
            Some(Component::ParentDir) => OsStr::new(".."),
            _ => OsStr::new(""),
        }
        .to_str()?;
        let next = last.checked_add(1)?;
        Some(format!(
            "SKILL.md in {parent} has {total} lines and you asked for {first}-{last}. A skill is \
             guidance to read to its end: read lines {next}-{total} (or the whole file) before relying on it."
        ))
    }
}

fn line_boundary(ch: char) -> bool {
    matches!(
        ch,
        '\n' | '\u{b}'
            | '\u{c}'
            | '\u{1c}'
            | '\u{1d}'
            | '\u{1e}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}
