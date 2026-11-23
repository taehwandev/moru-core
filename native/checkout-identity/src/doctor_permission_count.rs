//! owner: read-only command permission counting for doctor.
//! allowed imports: typed project and Node observations, JSON and std.
//! forbidden imports: permission grants, setup, command execution and writes.
//! callers/tests: completion probe, doctor report and native parity fixtures.
//! verification: Python command expansion, Node wildcard overlaps and fallbacks.
use super::{doctor_node_manifests::DoctorNodeManifests, doctor_project::DoctorProject};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::path::Path;

pub(super) struct DoctorPermissionCount;

impl DoctorPermissionCount {
    pub(super) fn inspect(payload: &Value) -> Option<Value> {
        let project = DoctorProject::project(payload)?;
        Some(json!({"count": Self::count(project)?}))
    }

    pub(super) fn count(project: &Path) -> Option<usize> {
        let markers = DoctorProject::read_permission_markers(project)?;
        let scripts = DoctorNodeManifests::script_groups(project)?;

        // Each build command has an exact and wildcard form. Python projects
        // also get one edit entry, even when they have no packaging manifest.
        let build_commands = 4 * usize::from(markers.swift)
            + 2 * usize::from(markers.gradle)
            + 5 * usize::from(markers.rust)
            + 7 * usize::from(markers.go)
            + 7 * usize::from(markers.python_packaged);
        let python_edit = usize::from(markers.python_packaged || markers.python_scripts);
        Some(2 * build_commands + python_edit + Self::node_count(&scripts))
    }

    fn node_count(groups: &[Vec<String>]) -> usize {
        if groups.is_empty() {
            return 0;
        }
        let mut commands = HashSet::new();
        let mut add = |command: String| {
            commands.insert(format!("{command} *"));
            commands.insert(command);
        };
        for name in groups.iter().flatten() {
            for runner in ["npm run", "bun run", "yarn", "pnpm run"] {
                add(format!("{runner} {name}"));
            }
        }
        for command in [
            "npm install",
            "npm i",
            "npm ci",
            "bun install",
            "bun i",
            "yarn install",
            "yarn",
            "pnpm install",
            "pnpm i",
        ] {
            add(command.to_owned());
        }
        commands.len()
    }
}
