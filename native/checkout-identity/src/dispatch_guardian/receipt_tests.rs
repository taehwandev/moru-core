use super::*;
use std::{
    os::unix::fs::{symlink, PermissionsExt},
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "moru-guardian-receipt-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn receipt_bytes_match_python_order_spacing_ascii_and_no_trailing_newline() {
    let f = Fixture::new();
    let path = f.0.join("receipt.json");
    let original = r#"{"run_id":"한글😀\u007f","task_id":"a\nb","attempt":1,"execution_id":"e","state":"admitted"}"#;
    fs::write(&path, original).unwrap();
    let value = DispatchGuardian::read_receipt(&path).unwrap();
    DispatchGuardian::save_receipt(&path, &value, "running", None).unwrap();
    assert_eq!(
        fs::read_to_string(&path).unwrap(),
        r#"{"run_id": "\ud55c\uae00\ud83d\ude00\u007f", "task_id": "a\nb", "attempt": 1, "execution_id": "e", "state": "running"}"#
    );
    DispatchGuardian::save_receipt(&path, &value, "finished", Some(137)).unwrap();
    assert!(fs::read_to_string(&path)
        .unwrap()
        .ends_with(r#""state": "finished", "returncode": 137}"#));
    assert_eq!(
        fs::metadata(&path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    assert_eq!(fs::read_dir(&f.0).unwrap().count(), 1);
}

#[test]
fn duplicate_keys_numeric_and_nested_values_keep_shared_json_semantics() {
    let value = PythonJson::parse(r#"{"attempt":100000000000000000000,"run_id":"old","run_id":"new","state":"admitted","returncode":[NaN,Infinity,-Infinity,1.0]}"#).unwrap();
    assert_eq!(
        DispatchGuardian::json(&value).unwrap(),
        r#"{"attempt": 100000000000000000000, "run_id": "new", "state": "admitted", "returncode": [NaN, Infinity, -Infinity, 1.0]}"#
    );
}

#[test]
fn symlink_and_contentful_receipts_are_refused_without_replacing_evidence() {
    let f = Fixture::new();
    let target = f.0.join("original");
    let link = f.0.join("receipt.json");
    fs::write(&target, b"original").unwrap();
    symlink(&target, &link).unwrap();
    let value = PythonJson::parse(r#"{"state":"admitted"}"#).unwrap();
    assert!(DispatchGuardian::save_receipt(&link, &value, "running", None).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"original");
    assert!(fs::symlink_metadata(&link)
        .unwrap()
        .file_type()
        .is_symlink());
    let value = PythonJson::parse(r#"{"state":"admitted","command":"private"}"#).unwrap();
    assert!(DispatchGuardian::save_receipt(&target, &value, "running", None).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"original");
    assert_eq!(fs::read_dir(&f.0).unwrap().count(), 2);
}

#[test]
fn failed_rename_removes_the_private_tempfile_and_keeps_uncertain_target() {
    let f = Fixture::new();
    let path = f.0.join("receipt.json");
    fs::create_dir(&path).unwrap();
    let value = PythonJson::parse(r#"{"state":"admitted"}"#).unwrap();
    assert!(DispatchGuardian::save_receipt(&path, &value, "running", None).is_err());
    assert_eq!(fs::read_dir(&f.0).unwrap().count(), 1);
    assert!(path.is_dir());
}
