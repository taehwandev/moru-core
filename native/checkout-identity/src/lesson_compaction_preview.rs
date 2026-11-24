//! owner: read-only report and advisory selection for lesson compaction.
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
        Self::report(input, false)
    }

    pub(super) fn apply_report(input: &Json) -> Option<Json> {
        Self::report(input, true)
    }

    fn report(input: &Json, apply: bool) -> Option<Json> {
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
        Self::report_at(inbox, limit, keys, days, cutoff, apply)
    }

    pub(super) fn dry_run(
        inbox: &str,
        limit: usize,
        keys: usize,
        days: i64,
        cutoff: i64,
    ) -> Option<Json> {
        Self::report_at(inbox, limit, keys, days, cutoff, false)
    }

    fn report_at(
        inbox: &str,
        limit: usize,
        keys: usize,
        days: i64,
        cutoff: i64,
        apply: bool,
    ) -> Option<Json> {
        let mut snapshot = LessonCompactionInbox::read(Path::new(inbox), limit)?;
        let lessons = snapshot.groups.len();
        let records: usize = snapshot.groups.iter().map(|(_, group)| group.len()).sum();
        let mut folds = Vec::new();
        let mut stale = Vec::new();
        snapshot.groups.sort_unstable_by(|(a, _), (b, _)| a.cmp(b));
        for (lesson, group) in snapshot.groups {
            let (names, records): (Vec<_>, Vec<_>) = group
                .into_iter()
                .map(|(name, record, _)| (name, record))
                .unzip();
            let needs_fold = names.len() != 1 || names.first()? != &format!("{lesson}.json");
            let merged = LessonCompactionMerge::merge(&records, keys, days)?;
            if LessonCompactionMerge::newly_stale(&merged, cutoff)? {
                stale.push(lesson.clone());
            }
            if needs_fold {
                let Value::Number(Number::Integer(count)) = &merged["occurrence_count"] else {
                    return None;
                };
                folds.push((lesson, names, count.clone()));
            }
        }
        let removed: usize = folds.iter().map(|(_, names, _)| names.len() - 1).sum();
        let mut output = format!(
            "inbox: {inbox}\nrecords: {records}  lessons: {lessons}\nlessons to fold: {}  files to remove: {removed}\nlessons to mark stale (unseen 14+ days): {}\n",
            folds.len(), stale.len()
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
        let mut displayed: Vec<_> = folds.iter().collect();
        displayed.sort_by_key(|(_, names, _)| Reverse(names.len()));
        for (lesson, names, count) in displayed.into_iter().take(5) {
            writeln!(
                output,
                "    {lesson}: {} files -> 1, occurrences {count}",
                names.len()
            )
            .ok()?;
        }
        if apply {
            let folds: Vec<_> = folds
                .into_iter()
                .map(|(lesson, names, _)| (lesson, names))
                .collect();
            return Some(
                json!({"output": output, "folds": folds, "stale": stale, "removed": removed}),
            );
        }
        output.push_str("nothing written; pass --apply to fold\n");
        Some(json!({"output": output}))
    }
}
