//! owner: read-only dry-run report for lesson compaction.
//! allowed imports: bounded lesson inbox, deterministic merge, and text formatting.
//! forbidden imports: writer locks, mutations and workflow authority.
//! callers/tests: lessons-compact dry run and test_lessons_compact.
//! verification: report counts, tie order, output limits and unchanged inbox.
use super::{
    lesson_compaction_inbox::LessonCompactionInbox, lesson_compaction_merge::LessonCompactionMerge,
};
use crate::python_json::{Number, Value};
use serde_json::{json, Value as Json};
use std::{cmp::Reverse, fmt::Write, path::Path};

pub(super) struct LessonCompactionPreview;

impl LessonCompactionPreview {
    pub(super) fn probe(input: &Json) -> Option<Json> {
        let inbox = input.get("inbox")?.as_str()?;
        let limit = input.get("digit_limit")?.as_u64()?.try_into().ok()?;
        let keys = input.get("key_limit")?.as_u64()?.try_into().ok()?;
        let days = input.get("recent_days")?.as_i64()?.checked_sub(1)?;
        if keys == 0 || days < 0 {
            return None;
        }
        let cutoff = LessonCompactionMerge::stale_cutoff(
            input.get("now")?.as_str()?,
            input.get("stale_days")?.as_i64()?,
        )?;
        let mut snapshot = LessonCompactionInbox::read(Path::new(inbox), limit)?;
        let lessons = snapshot.groups.len();
        let records: usize = snapshot.groups.iter().map(|(_, group)| group.len()).sum();
        let mut folds = Vec::new();
        let mut stale = 0;
        snapshot.groups.sort_unstable_by(|(a, _), (b, _)| a.cmp(b));
        for (lesson, group) in snapshot.groups {
            let length = group.len();
            let needs_fold = length != 1 || group.first()?.0 != format!("{lesson}.json");
            let group: Vec<_> = group.into_iter().map(|(_, record, _)| record).collect();
            let merged = LessonCompactionMerge::merge(&group, keys, days)?;
            if LessonCompactionMerge::newly_stale(&merged, cutoff)? {
                stale += 1;
            }
            if needs_fold {
                let Value::Number(Number::Integer(count)) = &merged["occurrence_count"] else {
                    return None;
                };
                folds.push((lesson, length, count.clone()));
            }
        }
        let removed: usize = folds.iter().map(|(_, length, _)| length - 1).sum();
        let mut output = format!(
            "inbox: {inbox}\nrecords: {records}  lessons: {lessons}\nlessons to fold: {}  files to remove: {removed}\nlessons to mark stale (unseen 14+ days): {stale}\n",
            folds.len()
        );
        if !snapshot.unreadable.is_empty() {
            writeln!(
                output,
                "unreadable, left untouched: {}",
                snapshot.unreadable.len()
            )
            .ok()?;
            for name in snapshot.unreadable.iter().take(5) {
                writeln!(output, "    {name}").ok()?;
            }
        }
        folds.sort_by_key(|(_, length, _)| Reverse(*length));
        for (lesson, length, count) in folds.iter().take(5) {
            writeln!(
                output,
                "    {lesson}: {length} files -> 1, occurrences {count}"
            )
            .ok()?;
        }
        output.push_str("nothing written; pass --apply to fold\n");
        Some(json!({"output": output}))
    }
}
