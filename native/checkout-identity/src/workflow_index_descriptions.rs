//! owner: parse document descriptions from caller-prepared Markdown index text.
//! allowed imports: Python whitespace rules, ordered JSON maps and string ranges.
//! forbidden imports: file access, search retrieval, vendor code and authority.
//! callers/tests: WorkflowQueryProcess; test_workflow_query_text.
//! verification: continuation joins, regex-equivalent matches and first wins.
use crate::python_text::PythonText;
use serde_json::{Map, Value};
use std::ops::Range;

pub(crate) struct IndexDescriptions;

impl IndexDescriptions {
    pub(crate) fn parse(text: &str) -> Map<String, Value> {
        let mut descriptions = Map::new();
        let mut pending = None::<String>;
        for line in text.split('\n') {
            let stripped = trim(line);
            if let Some(previous) = pending.as_mut() {
                if line.starts_with("  ") && !stripped.is_empty() {
                    previous.truncate(previous.trim_end_matches(PythonText::whitespace).len());
                    previous.push(' ');
                    previous.push_str(stripped);
                    continue;
                }
                Self::add_line(previous, &mut descriptions);
            }
            pending = Some(line.to_owned());
        }
        if let Some(line) = pending {
            Self::add_line(&line, &mut descriptions);
        }
        descriptions
    }

    fn add_line(line: &str, descriptions: &mut Map<String, Value>) {
        let stripped = trim(line);
        if !stripped.starts_with('-') {
            return;
        }
        let paths: Vec<_> = tokens(stripped).map(|(_, path)| path).collect();
        if paths.is_empty() {
            return;
        }
        let bullet = trim(stripped.trim_start_matches('-'));
        let mut description = String::new();
        let mut start = 0;
        for (range, _) in tokens(bullet) {
            description.push_str(&bullet[start..range.start]);
            start = range.end;
        }
        description.push_str(&bullet[start..]);
        let description = trim(trim(&description).trim_end_matches([':', ',']));
        for path in paths {
            if !descriptions.contains_key(path) {
                descriptions.insert(path.to_owned(), Value::String(description.to_owned()));
            }
        }
    }
}

fn trim(text: &str) -> &str {
    text.trim_matches(PythonText::whitespace)
}

fn tokens(text: &str) -> impl Iterator<Item = (Range<usize>, &str)> {
    let mut cursor = 0;
    std::iter::from_fn(move || loop {
        let open = cursor + text[cursor..].find('`')?;
        let close = open + 1 + text[open + 1..].find('`')?;
        let path = &text[open + 1..close];
        if path.len() > ".md".len() && path.ends_with(".md") {
            cursor = close + 1;
            return Some((open..cursor, path));
        }
        // A failed closing delimiter can begin the next regex match.
        cursor = close;
    })
}
