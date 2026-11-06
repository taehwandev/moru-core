use super::*;
use std::os::unix::fs::symlink;

#[test]
fn worker_shape_and_relative_paths_preserve_scope() {
    let base = env::temp_dir().join(format!("moru-next-worker-{}", std::process::id()));
    fs::create_dir_all(base.join(".moru/workers/one")).unwrap();
    let base = base.canonicalize().unwrap();
    let file = base.join(".moru/workers/one/preflight.json");
    fs::write(&file, "{}").unwrap();
    assert!(matches!(
        WorkerScope::parse(&base, " \u{85}\t", &base),
        Some(WorkerScope::Parent)
    ));
    assert!(
        matches!(WorkerScope::parse(&base, ".moru/workers/one/preflight.json", &base), Some(WorkerScope::Selected(path)) if path == file)
    );
    assert!(matches!(
        WorkerScope::parse(&base, ".moru/workers/missing/preflight.json", &base),
        Some(WorkerScope::Selected(_))
    ));
    assert!(matches!(
        WorkerScope::parse(&base, ".moru/workers/one/deeper/preflight.json", &base),
        Some(WorkerScope::Invalid)
    ));
    assert!(matches!(
        WorkerScope::parse(&base, ".moru/preflight.json", &base),
        Some(WorkerScope::Invalid)
    ));
    symlink("one", base.join(".moru/workers/alias")).unwrap();
    assert!(matches!(
        WorkerScope::parse(&base, ".moru/workers/alias/preflight.json", &base),
        Some(WorkerScope::Invalid)
    ));
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn linked_state_root_invalidates_even_real_worker_path() {
    let base = env::temp_dir().join(format!("moru-next-worker-linked-{}", std::process::id()));
    fs::create_dir_all(base.join("project")).unwrap();
    fs::create_dir_all(base.join("state/workers/one")).unwrap();
    let base = base.canonicalize().unwrap();
    let project = base.join("project");
    symlink(base.join("state"), project.join(".moru")).unwrap();
    let path = base.join("state/workers/one/preflight.json");
    fs::write(&path, "{}").unwrap();
    assert!(matches!(
        WorkerScope::parse(&project, path.to_str().unwrap(), &project),
        Some(WorkerScope::Invalid)
    ));
    assert!(matches!(
        WorkerScope::parse(&project, " \t", &project),
        Some(WorkerScope::Parent)
    ));
    fs::remove_dir_all(base).unwrap();
}
