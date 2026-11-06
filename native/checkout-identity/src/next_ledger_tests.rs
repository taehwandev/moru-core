use super::*;
use serde_json::json;
use sha2::{Digest, Sha256};
fn fixture() -> (std::path::PathBuf, Value, Vec<u8>, serde_json::Value) {
    let root = std::env::temp_dir().join(format!(
        "moru-next-ledger-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir(&root).unwrap();
    let root = root.canonicalize().unwrap();
    let evidence = root.join("preflight.json");
    let bytes = br#"{"route":{"gates":["tests"],"command":"small-change"}}"#.to_vec();
    fs::write(&evidence, &bytes).unwrap();
    let preflight = Py::parse(std::str::from_utf8(&bytes).unwrap()).unwrap();
    let ledger = json!({"schema_version":1,"preflight_evidence":evidence.to_str().unwrap(),"preflight_evidence_sha256":format!("{:x}",Sha256::digest(&bytes)),"route_fingerprint":"8b6832960b35eb89a7d5a81f2ac0a4e9e577602111d2428b1c0aa3a1c9853b76","entries":[]});
    (root, preflight, bytes, ledger)
}
#[test]
fn latest_records_clear_success_until_repaired() {
    let (root, p, bytes, mut ledger) = fixture();
    let evidence = root.join("preflight.json");
    let path = root.join("gate-evidence.json");
    let good = json!({"gate":"tests","status":"SUCCESS","fields":{"check":"unit","result":"1 passed"},"reuse_snapshot":{"schema_version":1}});
    for later in [
        json!({"gate":"tests","status":"FAIL"}),
        json!({"gate":"tests","status":"garbled"}),
        json!({"gate":"tests","status":"SUCCESS","fields":{"check":"unit"}}),
    ] {
        ledger["entries"] = json!([good.clone(), later]);
        fs::write(&path, ledger.to_string()).unwrap();
        assert!(NextLedger::read(&evidence, &path, &p, &bytes)
            .unwrap()
            .is_empty());
        ledger["entries"].as_array_mut().unwrap().push(good.clone());
        fs::write(&path, ledger.to_string()).unwrap();
        assert_eq!(
            NextLedger::read(&evidence, &path, &p, &bytes).unwrap(),
            BTreeSet::from(["tests".into()])
        );
    }
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn legacy_snapshot_and_content_freshness_stay_distinct() {
    let (root, p, bytes, mut ledger) = fixture();
    let evidence = root.join("preflight.json");
    let path = root.join("gate-evidence.json");
    ledger["entries"] = json!([{"gate":"tests","status":"SUCCESS","fields":{"check":false,"result":0},"reuse_snapshot":{"schema_version":true}}]);
    fs::write(&path, ledger.to_string()).unwrap();
    assert!(NextLedger::read(&evidence, &path, &p, &bytes)
        .unwrap()
        .contains("tests"));
    ledger["entries"][0]["reuse_snapshot"]["schema_version"] = json!(2);
    fs::write(&path, ledger.to_string()).unwrap();
    assert!(NextLedger::read(&evidence, &path, &p, &bytes)
        .unwrap()
        .is_empty());
    ledger["preflight_evidence_sha256"] = json!("stale");
    fs::write(&path, ledger.to_string()).unwrap();
    assert!(NextLedger::read(&evidence, &path, &p, &bytes)
        .unwrap()
        .is_empty());
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn surface_trailing_whitespace_and_generic_whitespace_match_reference() {
    let contract: serde_json::Value = serde_json::from_str(CONTRACT).unwrap();
    let c = &contract["ledger"];
    let entry=Py::parse(r#"{"fields":{"result":"resolved","owner":"owner","anchors":"anchor","evidence":"anchor -> owner","surface_paths":"path","concerns":"none","search_hops":"1","verification":"unknown\t"}}"#).unwrap();
    assert_eq!(
        fields::GateFields::recorded("work surface resolution", entry.as_object().unwrap(), c),
        Some(false)
    );
    let entry = Py::parse(r#"{"evidence":"   "}"#).unwrap();
    assert_eq!(
        fields::GateFields::recorded("custom", entry.as_object().unwrap(), c),
        Some(true)
    );
    let entry = Py::parse(r#"{"fields":{"execution_capsule_binding":"bound"}}"#).unwrap();
    assert_eq!(
        fields::GateFields::recorded("custom", entry.as_object().unwrap(), c),
        Some(false)
    );
}
