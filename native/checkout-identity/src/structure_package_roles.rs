//! owner: generic package findings from strict changed source paths.
//! allowed imports: JSON and standard-library collections.
//! forbidden imports: source reads, Git execution, writes and approval.
//! callers/tests: structural source layout batch and language root parity fixtures.
//! verification: parent ordering and Dart, Swift, JVM and administrative roots.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

pub(super) struct StructurePackageRoles;

#[derive(Default)]
struct Package {
    added: bool,
    dart: bool,
    swift: bool,
}

impl StructurePackageRoles {
    pub(super) fn failures(paths: &[Value], generic: &Value) -> Option<Value> {
        let generic = generic
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<BTreeSet<_>>>()?;
        let mut parents: BTreeMap<Vec<&str>, Package> = BTreeMap::new();
        for row in paths {
            let path = row.get(0)?.as_str()?;
            let mut parts = path.split('/').collect::<Vec<_>>();
            if parts.iter().any(|part| part.is_empty() || *part == ".") {
                return None;
            }
            let file = parts.pop()?;
            let package = parents.entry(parts).or_default();
            package.added |= row.get(1)?.as_str() == Some("A");
            if let Some((_, extension)) = file.rsplit_once('.') {
                package.dart |= extension.eq_ignore_ascii_case("dart");
                package.swift |= extension.eq_ignore_ascii_case("swift");
            }
        }
        let mut failures = Vec::new();
        for (parent, package) in parents {
            if !package.added {
                continue;
            }
            let parts = Self::package_parts(&parent, &package);
            let parts = parts.strip_prefix(&[".agents", "shared"]).unwrap_or(parts);
            if parts.iter().any(|part| !part.is_ascii()) {
                return None;
            }
            let matches = parts
                .iter()
                .copied()
                .filter(|part| generic.contains(part.to_ascii_lowercase().as_str()))
                .collect::<BTreeSet<_>>();
            if !matches.is_empty() {
                let parent = parent.join("/");
                let shown = matches.into_iter().collect::<Vec<_>>().join(", ");
                failures.push(format!(
                    "{parent} contains grab-bag package segment(s) {shown} for new \
                     runtime source; choose a package name that states the purpose, owner, or contract"
                ));
            }
        }
        Some(json!(failures))
    }

    fn package_parts<'a, 'b>(parts: &'a [&'b str], package: &Package) -> &'a [&'b str] {
        if package.dart {
            if let Some(index) = parts.iter().rposition(|part| *part == "lib") {
                let below = &parts[index + 1..];
                return below.strip_prefix(&["src"]).unwrap_or(below);
            }
        }
        if package.swift {
            if let Some(index) = parts.iter().rposition(|part| *part == "Sources") {
                return &parts[index + 1..];
            }
        }
        if let Some(index) = parts
            .windows(3)
            .position(|part| part[0] == "src" && matches!(part[2], "kotlin" | "java"))
        {
            return &parts[index + 3..];
        }
        parts
    }
}
