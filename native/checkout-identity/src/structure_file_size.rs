//! owner: file-size and line-addition diagnostics from prepared review facts.
//! allowed imports: JSON and standard-library formatting.
//! forbidden imports: filesystem changes, Git execution and approval decisions.
//! callers/tests: structural review via the private completion probe.
//! verification: exact threshold, rewrite and initial-build diagnostics.
use serde_json::{json, Value};

pub(super) struct StructureFileSize;

impl StructureFileSize {
    pub(super) fn batch(payload: &Value) -> Option<Value> {
        let rows = payload.get("files")?.as_array()?;
        if rows.len() > 4096 {
            return None;
        }
        let findings = rows.iter().map(Self::inspect).collect::<Option<Vec<_>>>()?;
        Some(json!({"findings": findings}))
    }

    fn inspect(row: &Value) -> Option<(Vec<String>, Vec<String>)> {
        let path = row.get("path")?.as_str()?;
        let lines = row.get("line_count")?.as_i64()?;
        let max_file = row.get("max_file_lines")?.as_i64()?;
        let max_added = row.get("max_added_lines")?.as_i64()?;
        let pressure = row.get("review_warning_file_lines")?.as_i64()?;
        let metadata = row.get("metadata")?.as_object()?;
        let mut failures = Vec::new();
        let mut warnings = Vec::new();
        if metadata
            .get("initial_full_build")
            .map_or(Some(false), Value::as_bool)?
        {
            if lines > pressure {
                warnings.push(format!(
                    "{path} is an initial full-build file with {lines} lines (no Git HEAD commit); \
                     per-commit line-addition caps do not block unbound full builds, \
                     but keep one clear module owner per file"
                ));
            }
            return Some((failures, warnings));
        }
        let added_file = metadata.get("status").map_or(Some(""), Value::as_str)? == "A";
        let added = match metadata.get("additions") {
            None | Some(Value::Null) => {
                if added_file {
                    lines
                } else {
                    0
                }
            }
            Some(value) => value.as_i64()?,
        };
        let deleted = metadata.get("deletions").map_or(Some(0), Value::as_i64)?;
        if added_file && lines > max_file {
            failures.push(format!(
                "{path} is a new development source/style file with {lines} lines; \
                 new-file hard limit is {max_file}; split by responsibility before approval"
            ));
        }
        if added > max_added {
            if !added_file && deleted > added {
                warnings.push(format!(
                    "{path} adds {added} lines but deletes {deleted} lines, so the file \
                     is not growing; structure-review evidence is required instead of an addition-limit failure"
                ));
            } else {
                failures.push(format!(
                    "{path} adds {added} lines in one development source/style file; \
                     per-file addition limit is {max_added}; split the change before approval. \
                     Move independently reviewable previews, demos, or samples to a subject-named \
                     sibling file, or extract the nearest real behavior owner"
                ));
            }
        }
        if !added_file && lines > max_file && added > 0 {
            warnings.push(format!(
                "{path} is already over {max_file} lines and adds {added} line(s); \
                 structure-review evidence is required and the new responsibility should be extracted \
                 when it expands the public owner surface"
            ));
        } else if lines > pressure {
            warnings.push(format!(
                "{path} is a changed development source/style file with {lines} lines; \
                 review-pressure limit is {pressure}; \
                 structure-review evidence is required before approving more behavior"
            ));
        }
        Some((failures, warnings))
    }
}
