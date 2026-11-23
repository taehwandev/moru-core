//! owner: native CLI orchestration for a ready execution capsule refresh.
//! allowed imports: capsule observations and atomic persistence, guarded reads, UTC and JSON.
//! forbidden imports: parent ledger mutation, gate issuance and providers.
//! callers/tests: launcher dispatch and CLI parity fixtures.
//! verification: no-Python refresh, Python-compatible record and refusal behavior.
use super::{
    capsule_artifact::CapsuleArtifact, capsule_check_cli::CapsuleCheck,
    capsule_directory::CapsuleDirectory, capsule_worktree_signature::WorktreeSignature,
};
use crate::{
    atomic_sibling::AtomicSibling, doc_transcript::DocTranscript, pretool_guard::CallbackGuard,
    python_text::PythonText, status_snapshot::StatusSnapshot,
};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fs::{self, File},
    io::{self, ErrorKind, Read, Write},
    os::unix::fs::MetadataExt,
    path::Path,
};

pub(crate) struct CapsuleRefresh;

impl CapsuleRefresh {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        let (project, rules, evidence) = CapsuleCheck::arguments(args, "refresh")?;
        CallbackGuard::root(launcher, "execution-capsule")?;
        let parent = evidence.parent()?;
        if evidence.file_name()?.to_str()? != "preflight.json"
            || parent.parent()? != project.join(".moru/runs")
        {
            return None;
        }
        let output = parent.join("execution-capsule.json");
        let output_text = output.to_str()?;
        let path_json = PythonText::json_ascii(output_text)?;
        let dir = AtomicSibling::open_directory(parent)?;
        let (preflight, preflight_hash) = CapsuleCheck::read_json_file(&dir, c"preflight.json")?;
        let (ledger, ledger_hash) = CapsuleCheck::read_json_file(&dir, c"gate-evidence.json")?;
        if !CapsuleCheck::path_matches(preflight.get("project")?, &project)
            || !CapsuleCheck::path_matches(preflight.get("rules")?, &rules)
        {
            return None;
        }
        let (route, identities) = CapsuleCheck::route_identities(&preflight)?;
        let route_hash = identities.get("route_fingerprint")?;
        CapsuleCheck::validate_ledger(ledger, &evidence, &preflight_hash, route_hash)?;
        let project_state = Self::observe_root(&project)?;
        let rules_state = if project == rules {
            project_state.clone()
        } else {
            Self::observe_root(&rules)?
        };
        let docs = DocTranscript::hash_documents(&rules, &CapsuleCheck::required_docs(route)?)?;
        let created_at = StatusSnapshot::capture_time()?;
        let mut entropy = [0; 16];
        File::open("/dev/urandom")
            .ok()?
            .read_exact(&mut entropy)
            .ok()?;
        let temporary: String = entropy.iter().map(|byte| format!("{byte:02x}")).collect();

        let named = fs::symlink_metadata(parent).ok()?;
        let opened = dir.metadata().ok()?;
        if (named.dev(), named.ino()) != (opened.dev(), opened.ino()) {
            return None;
        }
        match fs::symlink_metadata(&output) {
            Ok(meta) if meta.is_file() => {}
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            _ => return None,
        }
        let result = CapsuleArtifact::refresh_observed(
            &dir,
            &json!({
                "path": output_text, "temporary": temporary, "ledger_valid": true,
                "observed": {
                    "created_at": created_at, "required_docs": docs, "project_git": project_state,
                    "rules_git": rules_state, "route_fingerprint": route_hash,
                    "request_fingerprint": identities.get("request_fingerprint")?,
                },
            }),
            Some((&preflight_hash, &ledger_hash)),
        )?;

        // A returned result came from the atomic replacement attempt. Do not replay it.
        Some(Self::report(&result, output_text, &path_json))
    }

    fn observe_root(path: &Path) -> Option<Value> {
        let (root, code) = WorktreeSignature::git(path, &["rev-parse", "--show-toplevel"], 4096)?;
        if code == 128 && root.is_empty() {
            return CapsuleDirectory::observe(path);
        }
        if code != 0 || !CapsuleCheck::is_exact_git_root(path, &root)? {
            return None;
        }
        Self::observe_git(path)
    }

    fn observe_git(path: &Path) -> Option<Value> {
        let args = ["rev-parse", "--verify", "HEAD"];
        let (head, code) = WorktreeSignature::git(path, &args, 4096)?;
        if code != 0 {
            return None;
        }
        let observed = CapsuleCheck::worktree_state(path, true)?;
        let signature = observed.get("signature")?;
        if CapsuleCheck::worktree_state(path, false)?.get("signature")? != signature {
            return None;
        }
        let (after, code) = WorktreeSignature::git(path, &args, 4096)?;
        if code != 0 || after != head {
            return None;
        }
        Some(json!({
            "head": std::str::from_utf8(&head).ok()?.trim(),
            "worktree_fingerprint": observed.get("fingerprint")?,
            "worktree_signature": signature,
        }))
    }

    fn report(result: &Value, output: &str, path_json: &str) -> i32 {
        if result.get("errno").is_some_and(Value::is_null) {
            let line = format!("{{\"capsule\": {path_json}, \"phase\": \"ready\"}}\n");
            return i32::from(io::stdout().write_all(line.as_bytes()).is_err());
        }
        let reason = result["errno"]
            .as_i64()
            .and_then(|number| i32::try_from(number).ok())
            .map_or_else(
                || "native execution capsule replacement outcome could not be determined".into(),
                |number| {
                    let errno = io::Error::from_raw_os_error(number).to_string();
                    let suffix = format!(" (os error {number})");
                    let detail = errno.strip_suffix(&suffix).unwrap_or(&errno);
                    format!("[Errno {number}] {detail}: {}", PythonText::repr(output))
                },
            );
        if let Some(reason) = PythonText::json_ascii(&reason) {
            let _ = writeln!(
                io::stdout(),
                "{{\"reasons\": [{reason}], \"reusable\": false}}"
            );
        }
        1
    }
}
