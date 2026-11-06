use super::*;
use std::os::unix::fs::symlink;
#[test]
fn walk_orders_files_before_directories_and_excludes_nested_and_links() {
    let base = std::env::temp_dir().join(format!("moru-next-walk-{}", std::process::id()));
    fs::create_dir_all(&base).unwrap();
    let base = base.canonicalize().unwrap();
    for name in ["z", "a", "workers/one", "nested", "external"] {
        fs::create_dir_all(base.join(name)).unwrap();
    }
    for name in [
        "preflight.json",
        "z/preflight.json",
        "a/preflight.json",
        "workers/one/preflight.json",
        "nested/preflight.json",
        "external/ignored",
    ] {
        fs::write(base.join(name), "{}").unwrap();
    }
    symlink("missing", base.join("nested/.git")).unwrap();
    symlink(base.join("a"), base.join("linked-dir")).unwrap();
    symlink(
        base.join("preflight.json"),
        base.join("external/preflight.json"),
    )
    .unwrap();
    let result = NextWalk::read(&base, &BTreeSet::from(["preflight.json".into()])).unwrap();
    assert!(result.complete);
    assert_eq!(
        result.candidates,
        [
            base.join("preflight.json"),
            base.join("a/preflight.json"),
            base.join("z/preflight.json")
        ]
    );
    assert_eq!(result.workers, [base.join("workers/one/preflight.json")]);
    fs::remove_dir_all(base).unwrap();
}

#[test]
fn missing_scan_root_is_incomplete_but_empty_names_need_no_scan() {
    let missing =
        std::env::temp_dir().join(format!("moru-next-walk-missing-{}", std::process::id()));
    assert!(
        !NextWalk::read(&missing, &BTreeSet::from(["preflight.json".into()]))
            .unwrap()
            .complete
    );
    assert!(NextWalk::read(&missing, &BTreeSet::new()).unwrap().complete);
}
