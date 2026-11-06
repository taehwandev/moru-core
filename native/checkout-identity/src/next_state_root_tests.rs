use super::*;
use std::os::unix::fs::symlink;

#[test]
fn roots_resolve_without_global_marker_policy_or_invented_mapping() {
    let base = std::env::temp_dir().join(format!("moru-next-state-{}", std::process::id()));
    fs::create_dir_all(base.join("project")).unwrap();
    fs::create_dir_all(base.join("external")).unwrap();
    let base = base.canonicalize().unwrap();
    let project = base.join("project");
    let root = project.join(".moru");
    assert!(matches!(NextStateRoot::resolve(&project), Some(None)));
    symlink(base.join("external"), &root).unwrap();
    assert_eq!(
        NextStateRoot::resolve(&project),
        Some(Some(base.join("external")))
    );
    fs::write(root.join("moru-root"), "marker").unwrap();
    fs::write(root.join("projects.json"), "{}").unwrap();
    assert_eq!(
        NextStateRoot::resolve(&project),
        Some(Some(base.join("external")))
    );
    fs::remove_file(&root).unwrap();
    symlink("missing", &root).unwrap();
    assert!(NextStateRoot::resolve(&project).is_none());
    fs::remove_file(&root).unwrap();
    fs::write(&root, "not a directory").unwrap();
    assert!(NextStateRoot::resolve(&project).is_none());
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn resolved_keys_use_relative_inside_and_absolute_outside_project() {
    use super::super::candidates::Candidates;
    use sha2::{Digest, Sha256};
    let project = Path::new("/project");
    for (path, text) in [
        ("/project", "."),
        ("/project/state/preflight.json", "state/preflight.json"),
        ("/external/preflight.json", "/external/preflight.json"),
    ] {
        assert_eq!(
            Candidates::key(project, Path::new(path)),
            Some(format!("{:x}", Sha256::digest(text.as_bytes())))
        );
    }
}
