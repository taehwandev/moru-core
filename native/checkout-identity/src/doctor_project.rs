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

pub(super) struct DoctorProject {
    pub(super) swift: bool,
    pub(super) gradle: bool,
    pub(super) rust: bool,
    pub(super) go: bool,
    pub(super) python_packaged: bool,
    pub(super) python_scripts: bool,
}

struct RootMarkers {
    swift: bool,
    gradle: bool,
    rust: bool,
    go: bool,
    python_packaged: bool,
    python_source: bool,
}

const MAX_ENTRIES: usize = 8192;
const MAX_INSTRUCTIONS: u64 = 1024 * 1024;
const MANAGED_BEGIN: &str = "<!-- BEGIN MANAGED MORU CORE ROUTING -->";
const MANAGED_END: &str = "<!-- END MANAGED MORU CORE ROUTING -->";

impl DoctorProject {
    pub(super) fn inspect(payload: &Value) -> Option<Value> {
        let project = Self::project(payload)?;
        let stacks = Self::stacks(project)?;
        let (agents, managed) = Self::instructions(project)?;
        Some(json!({
            "stacks": stacks,
            "instructions": {"agents_md_present": agents, "managed_routing_block": managed},
        }))
    }

    pub(super) fn permission_markers(payload: &Value) -> Option<Value> {
        let project = Self::project(payload)?;
        let markers = Self::read_permission_markers(project)?;
        Some(json!({
            "swift": markers.swift,
            "gradle": markers.gradle,
            "rust": markers.rust,
            "go": markers.go,
            "python_packaged": markers.python_packaged,
            "python_scripts": markers.python_scripts,
        }))
    }

    pub(super) fn read_permission_markers(project: &Path) -> Option<Self> {
        let markers = Self::root_markers(project)?;
        Some(Self {
            swift: markers.swift,
            gradle: markers.gradle || Self::nested_gradle(project)?,
            rust: markers.rust,
            go: markers.go,
            python_packaged: markers.python_packaged,
            python_scripts: !markers.python_packaged
                && (markers.python_source || Self::child_python(project)?),
        })
    }

    pub(super) fn project(payload: &Value) -> Option<&Path> {
        let project = Path::new(payload.get("project")?.as_str()?);
        (project.is_absolute() && project.canonicalize().ok()? == project).then_some(project)
    }

    fn stacks(project: &Path) -> Option<Vec<&'static str>> {
        let markers = Self::root_markers(project)?;
        let scripts = match fs::metadata(project.join("scripts")) {
            Ok(metadata) => metadata.is_dir(),
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(_) => return None,
        };
        let candidates = [
            ("swift", markers.swift),
            ("node", project.join("package.json").try_exists().ok()?),
            ("gradle", markers.gradle),
            ("rust", markers.rust),
            ("go", markers.go),
            (
                "python",
                markers.python_packaged || markers.python_source || scripts,
            ),
        ];
        Some(
            candidates
                .into_iter()
                .filter_map(|(name, found)| found.then_some(name))
                .collect(),
        )
    }

    fn root_markers(project: &Path) -> Option<RootMarkers> {
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
        Some(RootMarkers {
            swift: exists("Package.swift")? || swift_name,
            gradle: exists("build.gradle.kts")?
                || exists("build.gradle")?
                || exists("settings.gradle.kts")?,
            rust: exists("Cargo.toml")?,
            go: exists("go.mod")?,
            python_packaged: exists("pyproject.toml")?
                || exists("setup.py")?
                || exists("requirements.txt")?,
            python_source: python_name,
        })
    }

    fn nested_gradle(project: &Path) -> Option<bool> {
        let mut pending = vec![(project.to_owned(), 0)];
        let mut seen = 0;
        while let Some((directory, depth)) = pending.pop() {
            if depth > 64 || !fs::symlink_metadata(&directory).ok()?.is_dir() {
                return None;
            }
            for entry in fs::read_dir(directory).ok()? {
                seen += 1;
                if seen > MAX_ENTRIES {
                    return None;
                }
                let entry = entry.ok()?;
                if entry.file_name() == "build.gradle.kts" {
                    return Some(true);
                }
                if entry.file_type().ok()?.is_dir() {
                    pending.push((entry.path(), depth + 1));
                }
            }
        }
        Some(false)
    }

    fn child_python(project: &Path) -> Option<bool> {
        let mut seen = 0;
        for entry in fs::read_dir(project).ok()? {
            seen += 1;
            if seen > MAX_ENTRIES {
                return None;
            }
            let entry = entry.ok()?;
            if entry.file_name().as_bytes().starts_with(b".") {
                continue;
            }
            let kind = entry.file_type().ok()?;
            if kind.is_symlink() && entry.path().is_dir() {
                return None;
            }
            if kind.is_dir() {
                for child in fs::read_dir(entry.path()).ok()? {
                    seen += 1;
                    if seen > MAX_ENTRIES {
                        return None;
                    }
                    if child.ok()?.file_name().as_bytes().ends_with(b".py") {
                        return Some(true);
                    }
                }
            }
        }
        Some(false)
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
