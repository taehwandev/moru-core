//! owner: locked persistence of lesson compaction and stale marking.
//! allowed imports: anchored file primitives, the shared merge, and Python JSON.
//! forbidden imports: workflow authority, network, and unlocked writes.
//! callers/tests: lessons-compact apply_plan and test_lessons_compact.
//! verification: writer lock, fresh inputs, exact canonical bytes and cleanup order.
use super::lesson_compaction_merge::LessonCompactionMerge;
use crate::{
    atomic_sibling::AtomicSibling,
    python_json::{InputDiagnostic, Object, PythonJson, Value},
};
use serde_json::{json, Value as Json};
use std::{
    collections::{BTreeSet, HashSet},
    ffi::{CStr, CString},
    fs::{self, File, Metadata},
    io::{self, Read},
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
    time::{Duration, Instant},
};

pub(super) struct LessonCompactionApply;

impl LessonCompactionApply {
    pub(super) fn batch(input: &Json) -> Option<io::Result<Json>> {
        let (run, is_fold): (fn(&Json) -> Option<io::Result<bool>>, _) =
            match input.get("phase")?.as_str()? {
                "fold" => (Self::apply, true),
                "mark" => (Self::mark_stale, false),
                _ => return None,
            };
        let items = input.get("items")?.as_array()?;
        if !(2..=128).contains(&items.len()) {
            return None;
        }
        let mut request = input.as_object()?.clone();
        request.remove("items");
        let mut request = Json::Object(request);
        let mut processed = 0;
        let mut changed = 0;
        let started = Instant::now();
        for item in items {
            if started.elapsed() >= Duration::from_secs(8) {
                break;
            }
            if is_fold {
                let Some(fold) = item.as_object() else { break };
                let (Some(lesson), Some(known)) = (fold.get("lesson_id"), fold.get("known")) else {
                    break;
                };
                request["lesson_id"] = lesson.clone();
                request["known"] = known.clone();
            } else {
                request["lesson_id"] = item.clone();
            }
            match run(&request) {
                Some(Ok(updated)) => {
                    processed += 1;
                    changed += usize::from(updated);
                }
                Some(Err(error)) => return Some(Err(error)),
                None => break,
            }
        }
        Some(Ok(json!({"processed": processed, "changed": changed})))
    }

    pub(super) fn apply(input: &Json) -> Option<io::Result<bool>> {
        let (inbox, lesson) = Self::location(input)?;
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
        let _lock = Self::lock(&directory, &canonical)?;
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
        Some(
            Self::replace(inbox, lesson, &directory, &target, merged)?
                .and_then(|()| {
                    remove
                        .into_iter()
                        .try_for_each(|(name, before)| Self::unlink(&directory, &name, &before))
                })
                .map(|()| true),
        )
    }

    pub(super) fn mark_stale(input: &Json) -> Option<io::Result<bool>> {
        let cutoff = LessonCompactionMerge::stale_cutoff(
            input.get("now")?.as_str()?,
            input.get("stale_days")?.as_i64()?,
        )?;
        Self::mark_at(input, cutoff)
    }

    pub(super) fn mark_at(input: &Json, cutoff: i64) -> Option<io::Result<bool>> {
        let (inbox, lesson) = Self::location(input)?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let directory = AtomicSibling::open_directory(inbox)?;
        let canonical = format!("{lesson}.json");
        let target = CString::new(canonical.as_str()).ok()?;
        let _lock = Self::lock(&directory, &canonical)?;
        let Some(file) = Self::open(&directory, &target).ok()? else {
            return Some(Ok(false));
        };
        if !file.metadata().ok()?.is_file() {
            return None;
        }
        let mut raw = String::new();
        file.take(64 * 1024 + 1).read_to_string(&mut raw).ok()?;
        if raw.len() > 64 * 1024 {
            return None;
        }
        let record = match PythonJson::parse_with_diagnostic(&raw, Some(limit), None) {
            Ok(Some(record)) if record.is_object() => record,
            Ok(Some(_)) | Err(InputDiagnostic::Syntax(_)) => return Some(Ok(false)),
            _ => return None,
        };
        if record["lesson_id"].as_str() != Some(lesson) {
            return None;
        }
        if !LessonCompactionMerge::newly_stale(&record, cutoff)? {
            return Some(Ok(false));
        }
        let Value::Object(mut record) = record else {
            return None;
        };
        record.insert("status".into(), Value::String("stale".into()));
        Some(
            Self::replace(inbox, lesson, &directory, &target, Value::Object(record))?
                .map(|()| true),
        )
    }

    fn location(input: &Json) -> Option<(&Path, &str)> {
        let inbox = Path::new(input.get("inbox")?.as_str()?);
        let lesson = input.get("lesson_id")?.as_str()?;
        (inbox.ends_with("lessons/inbox")
            && !lesson.is_empty()
            && lesson.len() <= 128
            && lesson
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-')))
        .then_some((inbox, lesson))
    }

    fn lock(directory: &File, canonical: &str) -> Option<File> {
        let name = CString::new(format!(".{canonical}.lock")).ok()?;
        // Python can establish a missing lock on first use.
        let lock = AtomicSibling::open_relative(directory, &name, libc::O_RDWR)?;
        (lock.metadata().ok()?.is_file()
            && unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0)
            .then_some(lock)
    }

    fn replace(
        inbox: &Path,
        lesson: &str,
        directory: &File,
        target: &CStr,
        record: Value,
    ) -> Option<io::Result<()>> {
        let pretty = PythonJson::render(&Self::sorted(record), true, true)?;
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
        if Self::open(directory, &temporary).ok()?.is_some() {
            return None;
        }
        let original = directory.metadata().ok()?;
        let current = fs::metadata(inbox).ok()?;
        if (original.dev(), original.ino()) != (current.dev(), current.ino()) {
            return None;
        }

        // Once replacement has started the result can never be a replayable decline.
        Some(AtomicSibling::InheritUmask.replace(directory, &temporary, target, text.as_bytes()))
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
