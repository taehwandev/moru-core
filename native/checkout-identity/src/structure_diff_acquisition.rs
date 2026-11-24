//! owner: bounded local Git acquisition for structural diff review.
//! allowed imports: read-only process capture, structural diff decoder and JSON.
//! forbidden imports: arbitrary commands, repository writes, review outcomes.
//! callers/tests: initial, working-tree and commit-range structural discovery.
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
    pub(super) fn removal_patch(input: &Value) -> Option<String> {
        let project = input.get("project")?.as_str()?;
        let root = Path::new(project);
        if !root.is_absolute() || root.canonicalize().ok()? != root {
            return None;
        }
        let paths = input.get("paths")?.as_array()?;
        if paths.len() > 128 {
            return None;
        }
        let paths = paths
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        if paths.iter().map(|path| path.len()).sum::<usize>() > 16 * 1024 {
            return None;
        }
        let revisions = match input.get("revisions")?.as_array()?.as_slice() {
            [head] if head.as_str()? == "HEAD" => vec!["HEAD"],
            [base, head] => vec![Self::commit(base)?, Self::commit(head)?],
            _ => return None,
        };
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut budget = 1024 * 1024;
        // Configured helpers stay with the original runner. They may have side effects
        // and must not be invoked by the native path before falling back.
        let helpers = Self::observe(
            project,
            &[
                "git",
                "config",
                "--name-only",
                "--get-regexp",
                "^(diff[.].*[.]textconv|core[.]fsmonitor|filter[.].*[.](clean|process))$",
            ],
            deadline,
            &mut budget,
        )?;
        if helpers["returncode"].as_i64()? != 1
            || helpers["stderr"].as_str()? != ""
            || helpers["stdout"].as_str()? != ""
        {
            return None;
        }
        let mut args = vec![
            "git",
            "-c",
            "core.fsmonitor=false",
            "diff",
            "-U0",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--diff-filter=ACDMRTUXB",
        ];
        args.extend(revisions);
        args.push("--");
        args.extend(paths);
        let patch = Self::run(project, &args, deadline, &mut budget)?;
        Some(patch.get("stdout")?.as_str()?.to_owned())
    }

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
        let untracked = input.get("untracked")?.as_bool()?;
        let mut budget = 128 * 1024;
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut commands = Map::new();
        let inspect_head = input.get("inspect_head").and_then(Value::as_bool) == Some(true);
        if inspect_head {
            if !untracked || !commits.is_null() {
                return None;
            }
            let (head, initial) = Self::working_head(project, deadline, &mut budget)?;
            commands.insert("rev_parse_head".into(), head);
            if initial {
                return Self::initial(project, &paths, deadline, &mut budget, commands);
            }
        }
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
        if untracked && !commits.is_null() {
            return None;
        }
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
            let observation = Self::list(project, &paths, false, deadline, &mut budget)?;
            payload["listings"] = json!([null, observation.get("stdout")?]);
            commands.insert("ls_files_untracked".to_owned(), observation);
        }
        let decoded = StructureDiff::decode(&payload)?;
        if inspect_head {
            Self::move_copy_candidates(project, &paths, deadline, &mut budget, &mut commands);
        }
        Some(json!({"commands": commands, "decoded": decoded}))
    }

    fn move_copy_candidates(
        project: &str,
        paths: &[&str],
        deadline: Instant,
        budget: &mut usize,
        commands: &mut Map<String, Value>,
    ) {
        let mut deleted = vec![
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=D",
            "HEAD",
            "--",
        ];
        deleted.extend_from_slice(paths);
        let tracked = ["git", "ls-files", "-z", "--cached", "--"];
        for (field, args) in [
            ("diff_deleted_paths", deleted.as_slice()),
            ("ls_files_copy_candidates", tracked.as_slice()),
        ] {
            if let Some(result) = Self::observe(project, args, deadline, budget) {
                commands.insert(field.into(), result);
            }
        }
    }

    fn working_head(project: &str, deadline: Instant, budget: &mut usize) -> Option<(Value, bool)> {
        let head = Self::observe(
            project,
            &["git", "rev-parse", "--verify", "HEAD"],
            deadline,
            budget,
        )?;
        if head["returncode"].as_i64()? != 0 {
            return Some((head, true));
        }
        let tree = Self::observe(
            project,
            &["git", "rev-parse", "--verify", "HEAD^{tree}"],
            deadline,
            budget,
        )?;
        let empty = tree["returncode"].as_i64()? == 0
            && matches!(
                tree["stdout"].as_str()?.trim(),
                "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
                    | "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321"
            );
        let initial = empty
            && Self::observe(
                project,
                &["git", "rev-parse", "--verify", "--quiet", "HEAD^"],
                deadline,
                budget,
            )?["returncode"]
                .as_i64()?
                != 0;
        Some((head, initial))
    }

    fn initial(
        project: &str,
        paths: &[&str],
        deadline: Instant,
        budget: &mut usize,
        mut commands: Map<String, Value>,
    ) -> Option<Value> {
        let tracked = Self::list(project, paths, true, deadline, budget)?;
        let untracked = Self::list(project, paths, false, deadline, budget)?;
        let decoded = StructureDiff::decode(&json!({
            "status": "", "numstat": "", "metadata": true,
            "listings": [tracked.get("stdout")?, untracked.get("stdout")?],
        }))?;
        commands.insert("ls_files_initial".into(), tracked);
        commands.insert("ls_files_untracked".into(), untracked);
        Some(json!({"commands": commands, "decoded": decoded}))
    }

    fn list(
        project: &str,
        paths: &[&str],
        include_cached: bool,
        deadline: Instant,
        budget: &mut usize,
    ) -> Option<Value> {
        let mut args = vec!["git", "ls-files", "-z"];
        if include_cached {
            args.push("--cached");
        }
        args.extend_from_slice(&["--others", "--exclude-standard", "--"]);
        args.extend_from_slice(paths);
        Self::run(project, &args, deadline, budget)
    }

    fn commit(value: &Value) -> Option<&str> {
        let oid = value.as_str()?;
        (matches!(oid.len(), 40 | 64) && oid.bytes().all(|byte| byte.is_ascii_hexdigit()))
            .then_some(oid)
    }

    fn run(project: &str, args: &[&str], deadline: Instant, budget: &mut usize) -> Option<Value> {
        let result = Self::observe(project, args, deadline, budget)?;
        (result["returncode"].as_i64()? == 0).then_some(result)
    }

    fn observe(
        project: &str,
        args: &[&str],
        deadline: Instant,
        budget: &mut usize,
    ) -> Option<Value> {
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
        if stdout.contains(&0x1b) || stderr.contains(&0x1b) {
            return None;
        }
        *budget = budget.checked_sub(stdout.len() + stderr.len())?;
        Some(json!({
            "command": args, "cwd": project, "returncode": status.code()?,
            "stdout": Text::universal_newlines(std::str::from_utf8(&stdout).ok()?),
            "stderr": Text::universal_newlines(std::str::from_utf8(&stderr).ok()?),
        }))
    }
}
