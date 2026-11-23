//! owner: read-only doctor inspection of project manifests and routing markers.
//! allowed imports: bounded local reads, JSON and standard-library paths.
//! forbidden imports: state mutation, launcher installation and permission grants.
//! callers/tests: completion probe, Python doctor report and native parity fixtures.
//! verification: stack order, glob semantics and managed instructions.
use crate::atomic_sibling::AtomicSibling;
use serde_json::{json, Value};
use std::{
    fs,
    io::{ErrorKind, Read},
    os::unix::{ffi::OsStrExt, fs::MetadataExt},
    path::Path,
};

pub(super) struct DoctorProject;

const MAX_ENTRIES: usize = 8192;
const MAX_INSTRUCTIONS: u64 = 1024 * 1024;
const MANAGED_BEGIN: &str = "<!-- BEGIN MANAGED MORU CORE ROUTING -->";
const MANAGED_END: &str = "<!-- END MANAGED MORU CORE ROUTING -->";

impl DoctorProject {
    pub(super) fn inspect(payload: &Value) -> Option<Value> {
        let project = Path::new(payload.get("project")?.as_str()?);
        if !project.is_absolute() || project.canonicalize().ok()? != project {
            return None;
        }
        let stacks = Self::stacks(project)?;
        let (agents, managed) = Self::instructions(project)?;
        Some(json!({
            "stacks": stacks,
            "instructions": {"agents_md_present": agents, "managed_routing_block": managed},
        }))
    }

    fn stacks(project: &Path) -> Option<Vec<&'static str>> {
        let mut swift_name = false;
        let mut python_name = false;
        for (index, entry) in fs::read_dir(project).ok()?.enumerate() {
            if index == MAX_ENTRIES {
                return None;
            }
            let name = entry.ok()?.file_name();
            let raw = name.as_bytes();
            swift_name |= raw.ends_with(b".xcodeproj") || raw.ends_with(b".xcworkspace");
            python_name |= raw.ends_with(b".py");
        }
        let exists = |name| project.join(name).try_exists().ok();
        let scripts = match fs::metadata(project.join("scripts")) {
            Ok(metadata) => metadata.is_dir(),
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(_) => return None,
        };
        let candidates = [
            ("swift", exists("Package.swift")? || swift_name),
            ("node", exists("package.json")?),
            (
                "gradle",
                exists("build.gradle.kts")?
                    || exists("build.gradle")?
                    || exists("settings.gradle.kts")?,
            ),
            ("rust", exists("Cargo.toml")?),
            ("go", exists("go.mod")?),
            (
                "python",
                exists("pyproject.toml")?
                    || exists("setup.py")?
                    || exists("requirements.txt")?
                    || python_name
                    || scripts,
            ),
        ];
        Some(
            candidates
                .into_iter()
                .filter_map(|(name, found)| found.then_some(name))
                .collect(),
        )
    }

    fn instructions(project: &Path) -> Option<(bool, bool)> {
        let named = match fs::symlink_metadata(project.join("AGENTS.md")) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == ErrorKind::NotFound => return Some((false, false)),
            Err(_) => return None,
        };
        if named.is_symlink() {
            return None;
        }
        if !named.is_file() {
            return Some((false, false));
        }
        let dir = AtomicSibling::open_directory(project)?;
        let file = AtomicSibling::open_relative(&dir, c"AGENTS.md", libc::O_RDONLY)?;
        let opened = file.metadata().ok()?;
        if (named.dev(), named.ino()) != (opened.dev(), opened.ino())
            || opened.len() > MAX_INSTRUCTIONS
        {
            return None;
        }
        let mut text = String::new();
        let size = file
            .take(MAX_INSTRUCTIONS + 1)
            .read_to_string(&mut text)
            .ok()?;
        if size as u64 > MAX_INSTRUCTIONS {
            return None;
        }
        Some((
            true,
            text.contains(MANAGED_BEGIN) && text.contains(MANAGED_END),
        ))
    }
}
