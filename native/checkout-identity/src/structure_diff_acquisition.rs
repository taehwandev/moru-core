//! owner: bounded local Git acquisition for structural diff review.
//! allowed imports: read-only process capture, structural diff decoder and JSON.
//! forbidden imports: arbitrary commands, repository writes, review outcomes.
//! callers/tests: working-tree and commit-range structural discovery.
//! verification: exact command evidence, scoped rename and untracked parity, fallback.
use super::structure_diff::StructureDiff;
use crate::{read_process::status::capture_status, text::Text};
use serde_json::{json, Map, Value};
use std::{
    path::Path,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

pub(super) struct StructureDiffAcquisition;

impl StructureDiffAcquisition {
    pub(super) fn probe(input: &Value) -> Option<Value> {
        let project = input.get("project")?.as_str()?;
        let root = Path::new(project);
        if !root.is_absolute() || root.canonicalize().ok()? != root {
            return None;
        }
        let paths = input
            .get("paths")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        if paths.len() > 128 || paths.iter().map(|path| path.len()).sum::<usize>() > 16 * 1024 {
            return None;
        }
        let commits = input.get("commits")?;
        let (prefix, revisions) = if commits.is_null() {
            ("diff", vec!["--relative", "HEAD"])
        } else {
            let [base, head] = commits.as_array()?.as_slice() else {
                return None;
            };
            (
                "commit_diff",
                vec![Self::commit(base)?, Self::commit(head)?],
            )
        };
        let untracked = input.get("untracked")?.as_bool()?;
        if untracked && !commits.is_null() {
            return None;
        }
        let mut budget = 128 * 1024;
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut commands = Map::new();
        for (flag, field) in [("--name-status", "name_status"), ("--numstat", "numstat")] {
            let mut args = vec!["git", "diff", flag, "-z", "--diff-filter=ACDMRTUXB"];
            args.extend_from_slice(&revisions);
            args.push("--");
            args.extend_from_slice(&paths);
            commands.insert(
                format!("{prefix}_{field}"),
                Self::run(project, &args, deadline, &mut budget)?,
            );
        }
        let mut payload = json!({
            "status": commands.get(&format!("{prefix}_name_status"))?.get("stdout")?,
            "numstat": commands.get(&format!("{prefix}_numstat"))?.get("stdout")?,
            "metadata": true,
        });
        if untracked {
            let mut args = vec![
                "git",
                "ls-files",
                "-z",
                "--others",
                "--exclude-standard",
                "--",
            ];
            args.extend_from_slice(&paths);
            let observation = Self::run(project, &args, deadline, &mut budget)?;
            payload["listings"] = json!([null, observation.get("stdout")?]);
            commands.insert("ls_files_untracked".to_owned(), observation);
        }
        let decoded = StructureDiff::decode(&payload)?;
        Some(json!({"commands": commands, "decoded": decoded}))
    }

    fn commit(value: &Value) -> Option<&str> {
        let oid = value.as_str()?;
        (matches!(oid.len(), 40 | 64) && oid.bytes().all(|byte| byte.is_ascii_hexdigit()))
            .then_some(oid)
    }

    fn run(project: &str, args: &[&str], deadline: Instant, budget: &mut usize) -> Option<Value> {
        let (stdout, stderr, status) = capture_status(
            Command::new("git")
                .args(&args[1..])
                .current_dir(project)
                .stdin(Stdio::null())
                .env("GIT_OPTIONAL_LOCKS", "0")
                .env("GIT_TERMINAL_PROMPT", "0")
                .env("GIT_NO_LAZY_FETCH", "1")
                .env("GIT_ALLOW_PROTOCOL", ""),
            deadline.checked_duration_since(Instant::now())?,
            Some(*budget as u64),
            None,
        )
        .ok()??;
        if !status.success() || stdout.contains(&0x1b) || stderr.contains(&0x1b) {
            return None;
        }
        *budget = budget.checked_sub(stdout.len() + stderr.len())?;
        Some(json!({
            "command": args, "cwd": project, "returncode": 0,
            "stdout": Text::universal_newlines(std::str::from_utf8(&stdout).ok()?),
            "stderr": Text::universal_newlines(std::str::from_utf8(&stderr).ok()?),
        }))
    }
}
