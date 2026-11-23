//! owner: shared execution-capsule CLI path and option admission.
//! allowed imports: standard-library argument decoding and local path identity.
//! forbidden imports: CLI writes, evidence validation, gate policy and providers.
//! callers/tests: check and refresh entrypoints and CLI parity fixtures.
//! verification: equivalent flag forms, aliases of the default path and fallback.
use std::{
    ffi::OsString,
    fs,
    io::ErrorKind,
    path::{Path, PathBuf},
};

pub(super) struct CapsuleArgs {
    pub(super) project: PathBuf,
    pub(super) rules: PathBuf,
    pub(super) evidence: PathBuf,
    pub(super) output: PathBuf,
}

impl CapsuleArgs {
    pub(super) fn parse(args: &[OsString], action: &str) -> Option<Self> {
        if args.get(1)? != action {
            return None;
        }
        let override_flag = match action {
            "check" => "--capsule",
            "refresh" => "--output",
            _ => return None,
        };
        let (mut project, mut rules, mut evidence, mut target) = (None, None, None, None);
        let mut options = args[2..].iter();
        while let Some(option) = options.next() {
            let option = option.to_str()?;
            let (flag, value) = match option.split_once('=') {
                Some((flag, value)) => (flag, value),
                None => {
                    let value = options.next()?.to_str()?;
                    if value.starts_with('-') {
                        return None;
                    }
                    (option, value)
                }
            };
            let slot = match flag {
                "--project" => &mut project,
                "--rules" => &mut rules,
                "--evidence" => &mut evidence,
                flag if flag == override_flag => &mut target,
                _ => return None,
            };
            if slot.is_some() || value.is_empty() {
                return None;
            }
            *slot = Some(Path::new(value));
        }
        let project = project?.canonicalize().ok()?;
        let rules = rules?.canonicalize().ok()?;
        let evidence = evidence?.canonicalize().ok()?;
        let parent = evidence.parent()?;
        if evidence.file_name()?.to_str()? != "preflight.json"
            || parent.parent()? != project.join(".moru/runs")
        {
            return None;
        }
        let output = parent.join("execution-capsule.json");
        if let Some(target) = target {
            if Self::resolve_target(target)? != output {
                return None;
            }
        }
        Some(Self {
            project,
            rules,
            evidence,
            output,
        })
    }

    fn resolve_target(path: &Path) -> Option<PathBuf> {
        match path.canonicalize() {
            Ok(resolved) => Some(resolved),
            Err(error) if error.kind() == ErrorKind::NotFound => {
                // Resolve a new file inside a real directory, without treating a
                // dangling output symlink as an unused path.
                let error = fs::symlink_metadata(path).err()?;
                if error.kind() != ErrorKind::NotFound {
                    return None;
                }
                Some(path.parent()?.canonicalize().ok()?.join(path.file_name()?))
            }
            Err(_) => None,
        }
    }
}
