//! owner: locked persistence of one supported lesson compaction fold.
//! allowed imports: anchored file primitives, the shared merge, and Python JSON.
//! forbidden imports: workflow authority, network, and unlocked writes.
//! callers/tests: lessons-compact apply_plan and test_lessons_compact.
//! verification: writer lock, fresh inputs, exact canonical bytes and cleanup order.
use super::lesson_compaction_merge::LessonCompactionMerge;
use crate::{
    atomic_sibling::AtomicSibling,
    python_json::{InputDiagnostic, Object, PythonJson, Value},
};
use serde_json::Value as Json;
use std::{
    collections::{BTreeSet, HashSet},
    ffi::{CStr, CString},
    fs::{self, File, Metadata},
    io::{self, Read},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
};

pub(super) struct LessonCompactionApply;

impl LessonCompactionApply {
    pub(super) fn apply(input: &Json) -> Option<io::Result<bool>> {
        let inbox = Path::new(input.get("inbox")?.as_str()?);
        let lesson = input.get("lesson_id")?.as_str()?;
        if !inbox.ends_with("lessons/inbox")
            || lesson.is_empty()
            || lesson.len() > 128
            || !lesson
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
        {
            return None;
        }
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let keys = input.get("key_limit")?.as_u64()?.try_into().ok()?;
        let days = input.get("recent_days")?.as_i64()?.checked_sub(1)?;
        if keys == 0 || days < 0 {
            return None;
        }
        let known = input.get("known")?.as_array()?;
        if known.len() > 4096 {
            return None;
        }
        let known = known
            .iter()
            .map(|name| {
                let name = name.as_str()?;
                (name.ends_with(".json") && Path::new(name).file_name()?.to_str()? == name)
                    .then_some(name)
            })
            .collect::<Option<Vec<_>>>()?;

        let directory = AtomicSibling::open_directory(inbox)?;
        let canonical = format!("{lesson}.json");
        let target = CString::new(canonical.as_str()).ok()?;
        let lock_name = CString::new(format!(".{canonical}.lock")).ok()?;
        // Only an existing lock is needed. Python can establish it on first use.
        let lock = AtomicSibling::open_relative(&directory, &lock_name, libc::O_RDWR)?;
        if !lock.metadata().ok()?.is_file()
            || unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0
        {
            return None;
        }
        let suffix = format!("-{canonical}");
        let mut names = BTreeSet::from([canonical.clone()]);
        for (index, entry) in fs::read_dir(inbox).ok()?.enumerate() {
            if index == 4096 {
                return None;
            }
            let name = entry.ok()?.file_name().into_string().ok()?;
            if name.ends_with(&suffix) {
                names.insert(name);
            }
        }
        let mut seen = HashSet::new();
        let mut records = Vec::new();
        let mut remove = Vec::new();
        let mut bytes = 0;
        for name in names
            .into_iter()
            .chain(known.into_iter().map(str::to_owned))
        {
            if !seen.insert(name.clone()) {
                continue;
            }
            let name = CString::new(name).ok()?;
            let Some(file) = Self::open(&directory, &name).ok()? else {
                continue;
            };
            let metadata = file.metadata().ok()?;
            if !metadata.is_file() {
                return None;
            }
            let mut raw = String::new();
            file.take(64 * 1024 + 1).read_to_string(&mut raw).ok()?;
            bytes += raw.len();
            if raw.len() > 64 * 1024 || bytes > 768 * 1024 {
                return None;
            }
            match PythonJson::parse_with_diagnostic(&raw, Some(limit), None) {
                Ok(Some(record)) if record.is_object() => {
                    if record["lesson_id"].as_str() == Some(lesson) {
                        records.push(record);
                        if name != target {
                            remove.push((name, metadata));
                        }
                    } else if name == target {
                        return None;
                    }
                }
                Err(InputDiagnostic::Syntax(_)) => {}
                _ => return None,
            }
        }
        if records.is_empty() {
            return Some(Ok(false));
        }
        let merged = LessonCompactionMerge::merge(&records, keys, days)?;
        let pretty = PythonJson::render(&Self::sorted(merged), true, true)?;
        // Python historically writes indented JSON with one space per level.
        let text = pretty
            .lines()
            .map(|line| {
                let spaces = line.len() - line.trim_start_matches(' ').len();
                &line[spaces / 2..]
            })
            .collect::<Vec<_>>()
            .join("\n");
        let temporary = CString::new(format!("{lesson}.compact.tmp")).ok()?;
        if Self::open(&directory, &temporary).ok()?.is_some() {
            return None;
        }
        let original = directory.metadata().ok()?;
        let current = fs::metadata(inbox).ok()?;
        if (original.dev(), original.ino()) != (current.dev(), current.ino()) {
            return None;
        }

        // Once replacement has started the result can never be a replayable decline.
        Some(
            AtomicSibling::InheritUmask
                .replace(&directory, &temporary, &target, text.as_bytes())
                .and_then(|()| {
                    remove
                        .into_iter()
                        .try_for_each(|(name, before)| Self::unlink(&directory, &name, &before))
                })
                .map(|()| true),
        )
    }

    fn open(directory: &File, name: &CStr) -> io::Result<Option<File>> {
        match AtomicSibling::open_relative_result(directory, name, libc::O_RDONLY) {
            Ok(file) => Ok(Some(file)),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error),
        }
    }

    fn unlink(directory: &File, name: &CStr, before: &Metadata) -> io::Result<()> {
        let Some(file) = Self::open(directory, name)? else {
            return Ok(());
        };
        let after = file.metadata()?;
        let identity = |meta: &Metadata| {
            (
                meta.dev(),
                meta.ino(),
                meta.len(),
                meta.mtime(),
                meta.mtime_nsec(),
            )
        };
        if identity(before) != identity(&after) {
            return Err(io::Error::other("lesson candidate changed before cleanup"));
        }
        if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) } == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        if error.kind() == io::ErrorKind::NotFound {
            Ok(())
        } else {
            Err(error)
        }
    }

    fn sorted(value: Value) -> Value {
        match value {
            Value::Object(values) => {
                let mut entries: Vec<_> = values.iter().collect();
                entries.sort_unstable_by(|(a, _), (b, _)| a.cmp(b));
                let mut sorted = Object::new();
                for (key, value) in entries {
                    sorted.insert(key.clone(), Self::sorted(value.clone()));
                }
                Value::Object(sorted)
            }
            Value::Array(values) => Value::Array(values.into_iter().map(Self::sorted).collect()),
            other => other,
        }
    }
}
