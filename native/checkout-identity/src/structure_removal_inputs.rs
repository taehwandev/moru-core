//! owner: bounded Git patch and untracked inputs for structural removal explanations.
//! allowed imports: local read-only file I/O, Python text boundaries and JSON.
//! forbidden imports: Git writes, matching decisions, sample rendering and logging source.
//! callers/tests: structural removal explanations and real Git parity fixtures.
//! verification: quoted paths, destination attribution, budget and filesystem fallback.
use crate::python_text::PythonText;
use serde_json::{json, Map, Value};
use std::{
    collections::HashMap,
    fs::{self, OpenOptions},
    io::Read,
    os::unix::fs::OpenOptionsExt,
    path::{Component, Path},
};

pub(super) struct StructureRemovalInputs;

struct Budget {
    remaining: usize,
    per_file: usize,
    used: HashMap<String, usize>,
}

impl Budget {
    fn take(&mut self, path: &str, size: usize) -> bool {
        let used = self.used.entry(path.to_owned()).or_default();
        if size > self.remaining || size > self.per_file - *used {
            return false;
        }
        *used += size;
        self.remaining -= size;
        true
    }
}

impl StructureRemovalInputs {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        Self::from_patch(input, input.get("diff")?.as_str()?)
    }

    pub(super) fn from_patch(input: &Value, text: &str) -> Option<Value> {
        let paths = input.get("untracked")?.as_array()?;
        let project = Path::new(input.get("project")?.as_str()?);
        let per_file = usize::try_from(input.get("per_file")?.as_u64()?).ok()?;
        let remaining = usize::try_from(input.get("total")?.as_u64()?).ok()?;
        if per_file > 200_000 || remaining > 1_000_000 || paths.len() > 256 {
            return None;
        }
        let mut budget = Budget {
            remaining,
            per_file,
            used: HashMap::new(),
        };
        let mut removed = Map::new();
        let mut added = Map::new();
        if !Self::parse(text, &mut budget, &mut removed, &mut added)? {
            return Some(json!({"truncated": true}));
        }
        if !paths.is_empty() && (!project.is_absolute() || project.canonicalize().ok()? != project)
        {
            return None;
        }
        for path in paths {
            let name = path.as_str()?;
            let Some(data) = Self::read(project, Path::new(name), per_file)? else {
                return Some(json!({"truncated": true}));
            };
            if data.len() > per_file || !budget.take(name, data.len()) {
                return Some(json!({"truncated": true}));
            }
            let text = String::from_utf8_lossy(&data);
            Self::lines(&mut added, name)
                .extend(PythonText::splitlines(&text).into_iter().map(Value::from));
        }
        Some(json!({"removed": removed, "added": added}))
    }

    fn parse(
        text: &str,
        budget: &mut Budget,
        removed: &mut Map<String, Value>,
        added: &mut Map<String, Value>,
    ) -> Option<bool> {
        let mut source = None;
        let mut destination = None;
        let mut in_header = false;
        for line in PythonText::splitlines(text) {
            if line.starts_with("diff --git ") {
                source = None;
                destination = None;
                in_header = true;
            } else if in_header {
                if let Some(path) = line.strip_prefix("--- ") {
                    source = Self::header_path(path, "a/")?;
                } else if let Some(path) = line.strip_prefix("+++ ") {
                    destination = Self::header_path(path, "b/")?;
                    in_header = false;
                }
            } else if let Some(path) = destination
                .as_deref()
                .filter(|path| !path.is_empty())
                .or(source.as_deref())
            {
                let (rows, content) = if let Some(content) = line.strip_prefix('+') {
                    (&mut *added, content)
                } else if let Some(content) = line.strip_prefix('-') {
                    (&mut *removed, content)
                } else {
                    continue;
                };
                if !budget.take(path, line.chars().count()) {
                    return Some(false);
                }
                Self::lines(rows, path).push(Value::from(content));
            }
        }
        Some(true)
    }

    fn lines<'a>(rows: &'a mut Map<String, Value>, path: &str) -> &'a mut Vec<Value> {
        rows.entry(path.to_owned())
            .or_insert_with(|| Value::Array(Vec::new()))
            .as_array_mut()
            .expect("line maps only store arrays")
    }

    fn header_path(raw: &str, prefix: &str) -> Option<Option<String>> {
        let raw = raw.trim_end_matches('\t');
        if raw == "/dev/null" {
            return Some(None);
        }
        let path = match raw
            .strip_prefix('"')
            .and_then(|value| value.strip_suffix('"'))
        {
            Some(quoted) => Self::unquote(quoted)?,
            None => raw.to_owned(),
        };
        Some(Some(path.strip_prefix(prefix).unwrap_or(&path).to_owned()))
    }

    fn unquote(quoted: &str) -> Option<String> {
        if !quoted.is_ascii() {
            return None;
        }
        let mut out = Vec::new();
        let mut bytes = quoted.bytes();
        while let Some(byte) = bytes.next() {
            let decoded = if byte == b'\\' {
                match bytes.next()? {
                    b'a' => 7,
                    b'b' => 8,
                    b'f' => 12,
                    b'n' => b'\n',
                    b'r' => b'\r',
                    b't' => b'\t',
                    b'v' => 11,
                    escaped @ (b'\\' | b'"') => escaped,
                    first @ b'0'..=b'3' => {
                        let [second, third] = [bytes.next()?, bytes.next()?];
                        if !(b'0'..=b'7').contains(&second) || !(b'0'..=b'7').contains(&third) {
                            return None;
                        }
                        (first - b'0') * 64 + (second - b'0') * 8 + (third - b'0')
                    }
                    _ => return None,
                }
            } else {
                byte
            };
            out.push(decoded);
        }
        Some(String::from_utf8_lossy(&out).into_owned())
    }

    fn read(project: &Path, relative: &Path, limit: usize) -> Option<Option<Vec<u8>>> {
        if relative.as_os_str().is_empty()
            || !relative
                .components()
                .all(|part| matches!(part, Component::Normal(_)))
        {
            return None;
        }
        let path = project.join(relative);
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            return Some(None);
        };
        if metadata.is_symlink() {
            return Some(None);
        }
        if !metadata.is_file() || !path.canonicalize().ok()?.starts_with(project) {
            return None;
        }
        let Ok(file) = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(&path)
        else {
            return Some(None);
        };
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut bytes = Vec::new();
        Some(
            file.take(limit as u64 + 1)
                .read_to_end(&mut bytes)
                .ok()
                .map(|_| bytes),
        )
    }
}
