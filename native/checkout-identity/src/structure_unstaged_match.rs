//! owner: bounded end-to-end matching for unstaged structural moves and copies.
//! allowed imports: local source reads, read-only baseline blobs, line matching and JSON.
//! forbidden imports: index writes, Git mutations and review policy changes.
//! callers/tests: structural review and real Git parity fixtures.
//! verification: ordered ties, missing and unsupported inputs, similarity threshold.
use super::{
    structure_move_matching::StructureMoveMatching,
    structure_review_baseline::StructureReviewBaseline, structure_source_read::StructureSourceRead,
};
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::{Component, Path},
};

pub(super) struct StructureUnstagedMatch;

impl StructureUnstagedMatch {
    pub(super) fn plan(payload: &Value) -> Option<Value> {
        let project = payload.get("project")?.as_str()?;
        let added = payload.get("added")?.as_array()?;
        if added.len() > 32 {
            return None;
        }
        let deleted = Self::by_name(payload.get("deleted")?.as_str()?)?;
        let tracked = Self::by_name(payload.get("tracked")?.as_str()?)?;
        let mut moves = Vec::new();
        let mut copies = Vec::new();
        let mut unmatched = Vec::new();
        for path in added {
            let path = path.as_str()?;
            if let Some(result) = Self::planned_match(project, path, &deleted, false)? {
                moves.push(result);
            } else {
                unmatched.push(path);
            }
        }
        for path in unmatched {
            if let Some(result) = Self::planned_match(project, path, &tracked, true)? {
                copies.push(result);
            }
        }
        Some(json!({"moves": moves, "copies": copies}))
    }

    fn by_name(listing: &str) -> Option<HashMap<&str, Vec<&str>>> {
        if !listing.is_empty() && !listing.ends_with('\0') {
            return None;
        }
        let mut groups = HashMap::<_, Vec<_>>::new();
        for path in listing.split('\0').filter(|path| !path.is_empty()) {
            let name = path.trim_end_matches('/').rsplit('/').next().unwrap_or("");
            groups.entry(name).or_default().push(path);
        }
        Some(groups)
    }

    fn planned_match(
        project: &str,
        path: &str,
        grouped: &HashMap<&str, Vec<&str>>,
        exclude_current: bool,
    ) -> Option<Option<Value>> {
        let name = path.rsplit('/').next()?;
        let candidates: Vec<&str> = grouped
            .get(name)
            .into_iter()
            .flatten()
            .copied()
            .filter(|candidate| !exclude_current || *candidate != path)
            .collect();
        if candidates.is_empty() {
            return Some(None);
        }
        let result = Self::probe(&json!({
            "project": project, "current_path": path, "candidates": candidates,
        }))?;
        let matched = result.get("match")?;
        Some((!matched.is_null()).then(|| json!([path, matched])))
    }

    pub(super) fn probe(payload: &Value) -> Option<Value> {
        let project = Path::new(payload.get("project")?.as_str()?);
        let current = Path::new(payload.get("current_path")?.as_str()?);
        if !project.is_absolute()
            || project.canonicalize().ok()? != project
            || current.as_os_str().is_empty()
            || !current
                .components()
                .all(|part| matches!(part, Component::Normal(_)))
            || !project
                .join(current)
                .canonicalize()
                .ok()?
                .starts_with(project)
        {
            return None;
        }
        let mut remaining = 128 * 1024;
        let current = StructureSourceRead::read(project, current, &mut remaining)?;
        if current == Value::Bool(false) {
            return Some(json!({"match": null}));
        }
        let current = StructureMoveMatching::lines(&current)?;
        let paths = payload.get("candidates")?.as_array()?;
        let baselines = StructureReviewBaseline::batch(&json!({
            "project": project, "revision": "HEAD", "paths": paths,
        }))?;
        let rows = baselines.get("rows")?.as_array()?;
        let mut sources = Vec::new();
        let mut matched_paths = Vec::new();
        for (path, row) in paths.iter().zip(rows) {
            if row == &Value::Bool(false) {
                continue;
            }
            // Replaying the whole match is necessary when any candidate is unsupported.
            sources.push(PythonText::splitlines(row.as_str()?));
            matched_paths.push(path.as_str()?);
        }
        let Some((index, matched)) = StructureMoveMatching::best(&current, &sources)? else {
            return Some(json!({"match": null}));
        };
        let previous = &sources[index];
        let total = previous.len() + current.len();
        let similarity = if total == 0 {
            1.0
        } else {
            2.0 * matched as f64 / total as f64
        };
        let result = (similarity >= 0.8).then_some((
            matched_paths[index],
            similarity,
            current.len() - matched,
            previous.len() - matched,
        ));
        Some(json!({"match": result}))
    }
}
