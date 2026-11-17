//! Actual launcher protocol; no installed runtime, providers or Python fallback.
use serde_json::{json, Value};
use std::io::Write;
use std::process::{Command, Output, Stdio};

fn probe(bytes: &[u8]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_moru-native-launcher"))
        .args(["offline-trace", "--behavior-trace-probe"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(bytes).unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn behavior_trace_protocol_preserves_duplicate_submissions() {
    let request = json!({"schema_version":1,"provider":"agy","case_id":"observed",
        "events":[{"event_type":"review.record_initialized"},
        {"event_type":"review.prompt_submitted"},{"event_type":"review.prompt_submitted"},
        {"event_type":"review.completed"},{"event_type":"review.finished","status":"ok"}]});
    let output = probe(&serde_json::to_vec(&request).unwrap());
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let trace: Value = serde_json::from_slice(&output.stdout).unwrap();
    let events = trace["runs"][0]["events"].as_array().unwrap();
    assert_eq!(
        events
            .iter()
            .filter(|e| e["kind"] == "prompt_submitted")
            .count(),
        2
    );
    assert_eq!(
        events.last().unwrap(),
        &json!({"kind":"final","status":"ok"})
    );
}

#[test]
fn behavior_trace_protocol_rejects_incomplete_and_content_bearing_input() {
    for events in [
        json!([{"event_type":"worker.result"}]),
        json!([{"event_type":"review.prompt_submitted","content":"private-marker"},
               {"event_type":"review.finished","status":"ok"}]),
    ] {
        let request =
            json!({"schema_version":1,"provider":"agy","case_id":"observed","events":events});
        let output = probe(&serde_json::to_vec(&request).unwrap());
        assert_eq!(output.status.code(), Some(2));
        assert!(output.stdout.is_empty());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("private-marker"));
    }
}

#[test]
fn behavior_trace_protocol_bounds_input_without_running_commands() {
    let output = probe(&vec![b' '; 4 * 1024 * 1024 + 1]);
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("input_too_large"));
}
