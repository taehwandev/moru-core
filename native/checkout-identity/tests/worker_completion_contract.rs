//! Actual completion protocol: a successful process cannot hide a blocked result.
use serde_json::json;
use std::io::Write;
use std::process::{Command, Output, Stdio};

fn probe(raw: &[u8]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_moru-native-launcher"))
        .args(["offline-worker", "--worker-completion-probe"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(raw).unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn completion_requires_valid_packet_and_explicit_findings_policy() {
    for (status, allowed, accepted) in [
        ("ok", false, true),
        ("blocked", false, false),
        ("needs_inspection", false, false),
        ("findings", false, false),
        ("findings", true, true),
    ] {
        let packet = json!({"schema_version":"worker_result_v1", "status":status,
            "summary":"verdict", "next_action":"inspect", "blockers":[], "changed_paths":[],
            "findings":[], "checks":[{"exit_code":0,"outcome":"pass"}], "artifacts":{}});
        let request = json!({"returncode":0,"allow_findings":allowed,"packet":packet});
        let output = probe(&serde_json::to_vec(&request).unwrap());
        assert!(output.status.success());
        assert!(output.stderr.is_empty());
        assert_eq!(
            String::from_utf8(output.stdout).unwrap(),
            format!("{accepted}\n")
        );
    }
}

#[test]
fn completion_protocol_rejects_invalid_or_oversized_input_without_echo() {
    for input in [b"private-invalid-json".to_vec(), vec![b' '; 16385]] {
        let output = probe(&input);
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
    let output = probe(br#"{"returncode":0,"allow_findings":true,"packet":null}"#);
    assert!(output.status.success());
    assert_eq!(output.stdout, b"false\n");
}
