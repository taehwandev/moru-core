//! owner: read-only native execution-capsule check for Git and directory roots.
//! allowed imports: existing capsule validators, guarded reads, JSON and SHA-256.
//! forbidden imports: file writes, ledger issuance, providers and new authority.
//! callers/tests: launcher dispatch and transported CLI parity fixtures.
//! verification: native-only matched state and legacy diagnostics on decline.
use super::{
    capsule_artifact::CapsuleArtifact, capsule_cli_args::CapsuleArgs,
    capsule_directory::CapsuleDirectory, capsule_doc_drift::CapsuleDocDrift, capsule_json_integers,
    capsule_ledger::CapsuleLedger, capsule_shape::CapsuleShape,
    capsule_worktree_signature::WorktreeSignature,
};
use crate::{
    atomic_sibling::AtomicSibling, pretool_guard::CallbackGuard, python_text::PythonText,
    route_identity::RouteIdentity,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    ffi::{CStr, OsString},
    fs::File,
    io::{self, ErrorKind, Read, Write},
    path::Path,
};

pub(crate) struct CapsuleCheck;

impl CapsuleCheck {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        let CapsuleArgs {
            project,
            rules,
            evidence,
            output,
        } = CapsuleArgs::parse(args, "check")?;
        CallbackGuard::root(launcher, "execution-capsule")?;
        let output_text = output.to_str()?;
        let resolved = output.canonicalize().ok()?;
        if resolved != output {
            return None;
        }
        let artifact = CapsuleArtifact::read(&json!({"path": output_text}))?;
        let capsule = artifact.get("record")?;
        if !capsule_json_integers(capsule)
            || CapsuleShape::capsule(capsule)?.is_some()
            || capsule.get("phase")?.as_str()? != "ready"
        {
            return None;
        }
        let dir = AtomicSibling::open_directory(evidence.parent()?)?;
        Self::validate(&dir, &project, &rules, &evidence, capsule)?;
        let path_json = PythonText::json_ascii(output_text)?;
        let line = format!("{{\"capsule\": {path_json}, \"reasons\": [], \"reusable\": true}}\n");
        Some(i32::from(io::stdout().write_all(line.as_bytes()).is_err()))
    }

    fn validate(
        dir: &File,
        project: &Path,
        rules: &Path,
        evidence: &Path,
        capsule: &Value,
    ) -> Option<()> {
        let (preflight, preflight_hash) =
            Self::read_bound(dir, c"preflight.json", capsule.get("preflight_evidence")?)?;
        let (ledger, ledger_hash) =
            Self::read_bound(dir, c"gate-evidence.json", capsule.get("gate_ledger")?)?;
        if !Self::path_matches(preflight.get("project")?, project)
            || !Self::path_matches(preflight.get("rules")?, rules)
            || ledger.get("invalid_json").is_some()
        {
            return None;
        }
        let (route, identities) = Self::route_identities(&preflight)?;
        let route_hash = identities.get("route_fingerprint")?;
        if route_hash != capsule.get("route_fingerprint")?
            || identities.get("request_fingerprint")? != capsule.get("request_fingerprint")?
        {
            return None;
        }
        let required = Self::required_docs(route)?;
        let recorded = capsule.get("required_docs")?;
        let names = recorded
            .as_array()?
            .iter()
            .map(|row| row.get("path")?.as_str())
            .collect::<Option<Vec<_>>>()?;
        if required != names {
            return None;
        }
        let docs = CapsuleDocDrift::compare(
            &json!({"rules": rules.to_str()?, "recorded": recorded, "updates": {}}),
        )?;
        if !Self::clean(&docs) {
            return None;
        }
        let project_state = capsule.get("project_git")?;
        let rules_state = capsule.get("rules_git")?;
        Self::check_root(project, project_state)?;
        if project == rules {
            if project_state != rules_state {
                return None;
            }
        } else {
            Self::check_root(rules, rules_state)?;
        }
        Self::validate_ledger(ledger, evidence, &preflight_hash, route_hash)?;
        let current_preflight = CapsuleArtifact::file_record(dir, c"preflight.json", false)??;
        let current_ledger = CapsuleArtifact::file_record(dir, c"gate-evidence.json", false)??;
        (current_preflight["sha256"].as_str()? == preflight_hash
            && current_ledger["sha256"].as_str()? == ledger_hash)
            .then_some(())
    }

    fn read_bound(dir: &File, name: &CStr, record: &Value) -> Option<(Value, String)> {
        if record.get("filename")?.as_str()? != name.to_str().ok()? {
            return None;
        }
        let (value, hash) = Self::read_json_file(dir, name)?;
        (hash == record.get("sha256")?.as_str()?).then_some((value, hash))
    }

    pub(super) fn read_json_file(dir: &File, name: &CStr) -> Option<(Value, String)> {
        Self::read_optional_json_file(dir, name)?
    }

    pub(super) fn read_optional_json_file(
        dir: &File,
        name: &CStr,
    ) -> Option<Option<(Value, String)>> {
        let file = match AtomicSibling::open_relative_result(dir, name, libc::O_RDONLY) {
            Ok(file) => file,
            Err(error) if error.kind() == ErrorKind::NotFound => return Some(None),
            Err(_) => return None,
        };
        let meta = file.metadata().ok()?;
        let limit = 1024 * 1024;
        if !meta.is_file() || meta.len() > limit {
            return None;
        }
        let mut bytes = Vec::new();
        file.take(limit + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > limit
            || bytes
                .split(|byte| !byte.is_ascii_digit())
                .any(|digits| digits.len() > 640)
        {
            return None;
        }
        let hash = format!("{:x}", Sha256::digest(&bytes));
        Some(Some((serde_json::from_slice(&bytes).ok()?, hash)))
    }

    pub(super) fn route_identities(preflight: &Value) -> Option<(&Value, Value)> {
        let route = preflight.get("route")?;
        let empty = json!({});
        let intake = preflight
            .get("request_intake")
            .filter(|value| value.is_object())
            .unwrap_or(&empty);
        if !capsule_json_integers(route) || !capsule_json_integers(intake) {
            return None;
        }
        let inputs = serde_json::to_vec(&json!({"route": route, "intake": intake})).ok()?;
        Some((route, RouteIdentity::probe(&inputs)?))
    }

    pub(super) fn validate_ledger(
        ledger: Value,
        evidence: &Path,
        hash: &str,
        route: &Value,
    ) -> Option<()> {
        Self::ledger_validity(ledger, evidence, hash, route)?.then_some(())
    }

    pub(super) fn ledger_validity(
        ledger: Value,
        evidence: &Path,
        hash: &str,
        route: &Value,
    ) -> Option<bool> {
        if ledger.get("invalid_json").is_some() {
            return None;
        }
        let Some(recorded) = ledger.get("preflight_evidence") else {
            return Some(false);
        };
        let path = Path::new(recorded.as_str()?);
        if !path.is_absolute() {
            return None;
        }
        let resolved = path.canonicalize().ok()?;
        let parent = CapsuleLedger::check(&json!({
            "ledger": ledger, "recorded_path": resolved.to_str()?, "observed_path": evidence.to_str()?,
            "observed_hash": hash, "observed_route": route,
        }))?;
        Some(Self::clean(&parent))
    }

    pub(super) fn path_matches(value: &Value, expected: &Path) -> bool {
        value.as_str().is_some_and(|text| {
            let path = Path::new(text);
            path.is_absolute() && path.canonicalize().ok().as_deref() == Some(expected)
        })
    }

    pub(super) fn required_docs(route: &Value) -> Option<Vec<&str>> {
        let values = match route.get("required_docs") {
            None | Some(Value::Null) => return Some(Vec::new()),
            Some(value) => value.as_array()?,
        };
        let names = values
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        Some(
            names
                .into_iter()
                .filter(|name| name.chars().any(|c| !PythonText::whitespace(c)))
                .collect(),
        )
    }

    fn clean(value: &Value) -> bool {
        value
            .get("failures")
            .and_then(Value::as_array)
            .is_some_and(Vec::is_empty)
    }

    fn check_root(path: &Path, recorded: &Value) -> Option<()> {
        let (root, code) = WorktreeSignature::git(path, &["rev-parse", "--show-toplevel"], 4096)?;
        if code == 128 && root.is_empty() {
            return CapsuleDirectory::matches_record(path, recorded);
        }
        if code != 0 || !Self::is_exact_git_root(path, &root)? {
            return None;
        }
        Self::check_git(path, recorded)
    }

    pub(super) fn is_exact_git_root(path: &Path, root: &[u8]) -> Option<bool> {
        Some(
            Path::new(std::str::from_utf8(root).ok()?.trim())
                .canonicalize()
                .ok()?
                == path,
        )
    }

    fn check_git(path: &Path, recorded: &Value) -> Option<()> {
        let head_args = ["rev-parse", "--verify", "HEAD"];
        let (head, code) = WorktreeSignature::git(path, &head_args, 4096)?;
        if code != 0 || recorded.get("head")?.as_str()? != std::str::from_utf8(&head).ok()?.trim() {
            return None;
        }
        Self::check_worktree(path, recorded)?;
        let (after, code) = WorktreeSignature::git(path, &head_args, 4096)?;
        (code == 0 && after == head).then_some(())
    }

    fn check_worktree(path: &Path, recorded: &Value) -> Option<()> {
        let capture = |strong| Self::worktree_state(path, strong);
        if capture(false)?.get("signature")? == recorded.get("worktree_signature")? {
            return Some(());
        }

        // A metadata change invalidates the shortcut, not the content binding.
        let snapshot = capture(true)?;
        if snapshot.get("fingerprint")? != recorded.get("worktree_fingerprint")? {
            return None;
        }
        (snapshot.get("signature")? == capture(false)?.get("signature")?).then_some(())
    }

    pub(super) fn worktree_state(path: &Path, strong: bool) -> Option<Value> {
        WorktreeSignature::capture(&json!({
            "path": path.to_str()?, "max_files": 5_000, "max_bytes": 256 * 1024 * 1024, "strong": strong,
        }))
    }
}
