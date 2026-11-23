//! owner: read-only native execution-capsule check for standard Git runs.
//! allowed imports: existing capsule validators, guarded reads, JSON and SHA-256.
//! forbidden imports: file writes, ledger issuance, providers and new authority.
//! callers/tests: launcher dispatch and transported CLI parity fixtures.
//! verification: native-only matched state and legacy diagnostics on decline.
use super::{
    capsule_artifact::CapsuleArtifact, capsule_doc_drift::CapsuleDocDrift, capsule_json_integers,
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
    io::{self, Read, Write},
    path::{Path, PathBuf},
};

pub(crate) struct CapsuleCheck;

impl CapsuleCheck {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        let (project, rules, evidence) = Self::arguments(args)?;
        CallbackGuard::root(launcher, "execution-capsule")?;
        let output = evidence.with_file_name("execution-capsule.json");
        if evidence.file_name()?.to_str()? != "preflight.json"
            || evidence.parent()?.parent()? != project.join(".moru/runs")
        {
            return None;
        }
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

    fn arguments(args: &[OsString]) -> Option<(PathBuf, PathBuf, PathBuf)> {
        if args.get(1)? != "check" || args.len() != 8 {
            return None;
        }
        let (mut project, mut rules, mut evidence) = (None, None, None);
        for pair in args[2..].chunks_exact(2) {
            let slot = match pair[0].to_str()? {
                "--project" => &mut project,
                "--rules" => &mut rules,
                "--evidence" => &mut evidence,
                _ => return None,
            };
            let value = pair[1].to_str()?;
            if slot.is_some() || value.is_empty() || value.starts_with('-') {
                return None;
            }
            *slot = Some(Path::new(value).canonicalize().ok()?);
        }
        Some((project?, rules?, evidence?))
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
        let identities = RouteIdentity::probe(&inputs)?;
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
        Self::check_git(project, project_state)?;
        if project == rules {
            if project_state != rules_state {
                return None;
            }
        } else {
            Self::check_git(rules, rules_state)?;
        }
        if !Self::path_matches(ledger.get("preflight_evidence")?, evidence) {
            return None;
        }
        let parent = CapsuleLedger::check(&json!({
            "ledger": ledger, "recorded_path": evidence.to_str()?, "observed_path": evidence.to_str()?,
            "observed_hash": preflight_hash, "observed_route": route_hash,
        }))?;
        if !Self::clean(&parent) {
            return None;
        }
        let current_preflight = CapsuleArtifact::file_record(dir, c"preflight.json", false)??;
        let current_ledger = CapsuleArtifact::file_record(dir, c"gate-evidence.json", false)??;
        (current_preflight["sha256"].as_str()? == preflight_hash
            && current_ledger["sha256"].as_str()? == ledger_hash)
            .then_some(())
    }

    fn read_bound(dir: &File, name: &CStr, record: &Value) -> Option<(Value, String)> {
        let filename = name.to_str().ok()?;
        if record.get("filename")?.as_str()? != filename {
            return None;
        }
        let file = AtomicSibling::open_relative(dir, name, libc::O_RDONLY)?;
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
        if hash != record.get("sha256")?.as_str()? {
            return None;
        }
        Some((serde_json::from_slice(&bytes).ok()?, hash))
    }

    fn path_matches(value: &Value, expected: &Path) -> bool {
        value.as_str().is_some_and(|text| {
            let path = Path::new(text);
            path.is_absolute() && path.canonicalize().ok().as_deref() == Some(expected)
        })
    }

    fn required_docs(route: &Value) -> Option<Vec<&str>> {
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

    fn check_git(path: &Path, recorded: &Value) -> Option<()> {
        let (root, code) = WorktreeSignature::git(path, &["rev-parse", "--show-toplevel"], 4096)?;
        if code != 0
            || Path::new(std::str::from_utf8(&root).ok()?.trim())
                .canonicalize()
                .ok()?
                .as_path()
                != path
        {
            return None;
        }
        let head_args = ["rev-parse", "--verify", "HEAD"];
        let (head, code) = WorktreeSignature::git(path, &head_args, 4096)?;
        if code != 0 || recorded.get("head")?.as_str()? != std::str::from_utf8(&head).ok()?.trim() {
            return None;
        }
        let observed = WorktreeSignature::capture(&json!({
            "path": path.to_str()?, "max_files": 5_000, "max_bytes": 256 * 1024 * 1024,
        }))?;
        if observed.get("signature")? != recorded.get("worktree_signature")? {
            return None;
        }
        let (after, code) = WorktreeSignature::git(path, &head_args, 4096)?;
        (code == 0 && after == head).then_some(())
    }
}
