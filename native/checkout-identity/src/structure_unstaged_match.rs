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
use std::path::{Component, Path};

pub(super) struct StructureUnstagedMatch;

impl StructureUnstagedMatch {
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
