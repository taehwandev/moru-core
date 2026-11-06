use super::*;
use std::os::unix::fs::{symlink, PermissionsExt};
fn root() -> PathBuf {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    loop {
        let path = std::env::temp_dir().join(format!(
            "moru-input-capture-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        match fs::create_dir(&path) {
            Ok(()) => return path.canonicalize().unwrap(),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => panic!("create input-capture fixture: {error}"),
        }
    }
}
#[test]
fn python_default_json_golden_preserves_mode_missing_unicode_and_target() {
    let root = root();
    fs::write(root.join("a"), b"abc").unwrap();
    fs::set_permissions(root.join("a"), fs::Permissions::from_mode(0o640)).unwrap();
    fs::write(root.join("한😀"), b"").unwrap();
    fs::set_permissions(root.join("한😀"), fs::Permissions::from_mode(0o600)).unwrap();
    symlink("../x😀", root.join("link")).unwrap();
    let paths = ["한😀", "missing", "link", "a", "a"].map(str::to_owned);
    assert_eq!(
        InputCapture::capture(&root, &paths),
        Some(Some(
            "e8515968970cc015563f187a36010a9f88134c070e1d3990300fba14cc2ee6ea".into()
        ))
    );
    assert_eq!(
        InputCapture::quote("한😀\x7f\n"),
        r#""\ud55c\ud83d\ude00\u007f\n""#
    );
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn limits_invalid_scope_and_metadata_changes_invalidate() {
    let root = root();
    fs::write(root.join("a"), b"abc").unwrap();
    assert_eq!(
        InputCapture::bounded(&root, &["a".into(), "a".into()], 1, 100),
        Some(None)
    );
    assert_eq!(
        InputCapture::bounded(&root, &["a".into()], 1, 2),
        Some(None)
    );
    for path in ["", "../a", ".git/config", "/absolute", "."] {
        assert_eq!(
            InputCapture::capture(&root, &[path.into()]),
            Some(None),
            "{path}"
        );
    }
    let before = fs::metadata(root.join("a")).unwrap();
    let digest = InputCapture::capture(&root, &["a".into()]);
    fs::set_permissions(root.join("a"), fs::Permissions::from_mode(0o700)).unwrap();
    assert_ne!(
        InputCapture::stamp(&before),
        InputCapture::stamp(&fs::metadata(root.join("a")).unwrap())
    );
    assert_ne!(digest, InputCapture::capture(&root, &["a".into()]));
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn parent_symlinks_rejected_but_final_link_is_hashed_first() {
    let root = root();
    fs::create_dir(root.join("real")).unwrap();
    fs::write(root.join("real/a"), b"abc").unwrap();
    symlink("real", root.join("parent")).unwrap();
    symlink("a", root.join("real/leaf")).unwrap();
    assert_eq!(
        InputCapture::capture(&root, &["parent/a".into()]),
        Some(None)
    );
    assert!(InputCapture::capture(&root, &["parent/leaf".into()])
        .unwrap()
        .is_some());
    symlink("missing", root.join("dangling")).unwrap();
    assert!(InputCapture::capture(&root, &["dangling/a".into()]).is_none());
    fs::remove_dir_all(root).unwrap();
}
