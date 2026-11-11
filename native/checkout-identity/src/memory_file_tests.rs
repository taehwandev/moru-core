use super::*;
use std::{
    io::{Seek, SeekFrom},
    os::unix::fs::symlink,
};

fn record(id: &str) -> Value {
    let mut record = json!({"schema_version":1,"id":id,"status":"active","scope":"task",
        "body":"checked synthetic","source":"source","review_on":"2099-01-01"});
    record["digest"] = json!(MemoryJson::digest(&record).unwrap());
    record
}
fn directory() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!(
        "moru-memory-native-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir(&path).unwrap();
    path.canonicalize().unwrap()
}
fn query(operation: &str, path: &Path) -> Option<Value> {
    MemoryFiles::evaluate(
        operation,
        &json!({"unicode":MemoryTerms::version(),"path":path.to_str().unwrap()}),
    )
}

#[test]
fn source_canonical_digest_unicode_quote_and_key_order_vector() {
    let record = json!({"review_on":"2099-01-01","scope":"task","source":"checked","body":"한글 😀 quote \""});
    assert_eq!(
        MemoryJson::digest(&record).unwrap(),
        "9f7593935407e9e19cdd4839bb359045af3bb63ad4004f0dad9d2c9b7a171fbb"
    );
}
#[test]
fn invalid_and_unsupported_decodes_remain_distinct_and_metadata_types_survive() {
    for bytes in [b"invalid".as_slice(), b"\xff", b"\xef\xbb\xbf{}"] {
        assert!(matches!(MemoryJson::decode(bytes), Some(None)));
    }
    for bytes in [
        b"{\"unused\":NaN}".as_slice(),
        b"{\"unused\":18446744073709551616}",
        b"{\"unused\":\"\\ud800\"}",
    ] {
        assert!(MemoryJson::decode(bytes).is_none());
    }
    let decoded = MemoryJson::decode(br#"{"z":1,"a":true,"z":1.0,"negative":-0.0}"#)
        .unwrap()
        .unwrap();
    assert!(decoded["z"].as_number().unwrap().is_f64());
    assert_eq!(
        decoded
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        vec!["z", "a", "negative"]
    );
    assert!(decoded["negative"].as_f64().unwrap().is_sign_negative());
}
#[test]
fn real_read_and_sorted_scan_reject_corruption_and_final_links() {
    let directory = directory();
    let a = record(&"a".repeat(16));
    let b = record(&"b".repeat(16));
    let path = directory.join("aaaaaaaaaaaaaaaa.json");
    fs::write(directory.join("bbbbbbbbbbbbbbbb.json"), b.to_string()).unwrap();
    fs::write(&path, a.to_string()).unwrap();
    fs::write(directory.join("bad.json"), "invalid").unwrap();
    symlink(&path, directory.join("link.json")).unwrap();
    fs::create_dir(directory.join("folder.json")).unwrap();
    assert_eq!(query("record", &path), Some(json!({"record":a})));
    assert_eq!(
        query("scan", &directory),
        Some(json!({"records":[a,b],"unreadable":3}))
    );
    fs::write(&path, "{\"schema_version\":999}").unwrap();
    assert_eq!(query("record", &path), Some(json!({"record":null})));
    fs::remove_dir_all(directory).unwrap();
}
#[test]
fn stream_and_inherited_descriptor_are_not_consumed() {
    let directory = directory();
    let fifo = directory.join("fifo.json");
    let raw = CString::new(fifo.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(raw.as_ptr(), 0o600) }, 0);
    assert!(query("record", &fifo).is_none());
    assert!(query("scan", &directory).is_none());
    let path = directory.join("aaaaaaaaaaaaaaaa.json");
    fs::write(&path, record(&"a".repeat(16)).to_string()).unwrap();
    let mut file = File::open(&path).unwrap();
    file.seek(SeekFrom::Start(3)).unwrap();
    let alias = std::path::PathBuf::from(format!("/dev/fd/{}", file.as_raw_fd()));
    let outcome = query("record", &alias);
    assert!(outcome.is_none() || outcome == Some(json!({"record":null})));
    assert_eq!(file.stream_position().unwrap(), 3);
    fs::remove_dir_all(directory).unwrap();
}
#[test]
fn unsupported_date_forms_decline_without_declaring_invalid_or_mutating() {
    let mut value = record(&"a".repeat(16));
    value["review_on"] = json!("20990101");
    value["digest"] = json!(MemoryJson::digest(&value).unwrap());
    assert!(MemoryRecord::valid(&value, "aaaaaaaaaaaaaaaa.json").is_none());
    value["review_on"] = json!("2099-02-30");
    assert_eq!(
        MemoryRecord::valid(&value, "aaaaaaaaaaaaaaaa.json"),
        Some(false)
    );
}
