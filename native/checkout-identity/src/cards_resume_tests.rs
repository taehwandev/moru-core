use super::CardResume;
use serde_json::{json, Value};
use std::{
    ffi::CString,
    fs,
    os::unix::{ffi::OsStrExt, fs::symlink},
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

const WORK: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const RUN: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const SESSION: &str = "abcdef01-2345-6789-abcd-ef0123456789";
const MAX_SESSION: &str = "ffffffff-ffff-ffff-ffff-ffffffffffff";
const MENU: &str = "1. summary [done, 😀123456789]";
struct Fixture {
    root: PathBuf,
    project: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "moru-card-resume-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let project = root.join("project");
        fs::create_dir(&project).unwrap();
        Self { root, project }
    }
    fn evidence(&self, run: &str, contents: &[u8]) -> PathBuf {
        let path = self
            .project
            .join(".moru/runs")
            .join(run)
            .join("preflight.json");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, contents).unwrap();
        path
    }
    fn legacy(&self) -> Value {
        let mut row = card(SESSION);
        set(&mut row, "runtime", json!(["null"]));
        set(&mut row, "session_id", json!(["null"]));
        set(
            &mut row,
            "project",
            json!(["text", self.project.to_str().unwrap()]),
        );
        row
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn card(session: &str) -> Value {
    json!([
        ["work_id", ["text", WORK]],
        ["run_id", ["text", RUN]],
        ["project", ["text", "unused"]],
        ["runtime", ["text", "codex"]],
        ["session_id", ["text", session]],
        ["summary", ["text", "summary"]],
        ["state", ["text", "done"]],
        ["updated_at", ["text", "😀123456789X"]]
    ])
}
fn set(row: &mut Value, name: &str, cell: Value) {
    row.as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|pair| pair[0] == name)
        .unwrap()[1] = cell;
}
fn payload(session: &str) -> Vec<u8> {
    serde_json::to_vec(
        &json!({"work":{"id":WORK},"runtime_session":{"runtime":"codex","session_id":session}}),
    )
    .unwrap()
}
fn menu(row: Value) -> Option<Vec<(String, String)>> {
    CardResume::menu(&json!([row]))
}

#[test]
fn direct_binding_accepts_all_uuid_bits_and_ignores_unused_work_project_and_run_fields() {
    for session in [SESSION, MAX_SESSION, "00000000-0000-0000-0000-000000000000"] {
        let mut row = card(session);
        for name in ["work_id", "run_id", "project"] {
            set(&mut row, name, json!(["unsupported", "ignored"]));
        }
        assert_eq!(menu(row), Some(vec![(MENU.into(), session.into())]));
    }
}

#[test]
fn uuid_spelling_is_exact_and_invalid_explicit_bindings_never_use_legacy_evidence() {
    let fixture = Fixture::new();
    fixture.evidence(RUN, &payload(SESSION));
    for invalid in [
        "ABCDEF01-2345-6789-ABCD-EF0123456789",
        "abcdef0123456789abcdef0123456789",
        "{abcdef01-2345-6789-abcd-ef0123456789}",
        "--last",
        "abcdef01-2345-6789-abcd-ef0123456789\n",
    ] {
        let mut row = fixture.legacy();
        set(&mut row, "runtime", json!(["text", "codex"]));
        set(&mut row, "session_id", json!(["text", invalid]));
        set(&mut row, "summary", json!(["blob", "ff"]));
        assert_eq!(menu(row), Some(vec![]), "{invalid}");
    }
    for (runtime, session) in [
        (json!(["text", ""]), json!(["text", SESSION])),
        (json!(["text", "agy"]), json!(["text", ""])),
        (json!(["text", "codex"]), json!(["null"])),
    ] {
        let mut row = fixture.legacy();
        set(&mut row, "runtime", runtime);
        set(&mut row, "session_id", session);
        assert_eq!(menu(row), Some(vec![]));
    }
}

#[test]
fn sqlite_falsey_cells_allow_legacy_and_falsey_run_ids_fall_back_to_work_id() {
    let fixture = Fixture::new();
    let path = fixture.evidence(WORK, &payload(SESSION));
    let before = fs::read(&path).unwrap();
    for empty in [
        json!(["null"]),
        json!(["text", ""]),
        json!(["integer", 0]),
        json!(["real", "-0.0"]),
        json!(["blob", ""]),
    ] {
        let mut row = fixture.legacy();
        for name in ["runtime", "session_id", "run_id"] {
            set(&mut row, name, empty.clone());
        }
        assert_eq!(menu(row), Some(vec![(MENU.into(), SESSION.into())]));
    }
    let mut row = fixture.legacy();
    row.as_array_mut()
        .unwrap()
        .retain(|pair| pair[0] != "run_id");
    assert_eq!(menu(row), Some(vec![(MENU.into(), SESSION.into())]));
    assert_eq!(before, fs::read(path).unwrap());
}

#[test]
fn legacy_matches_exact_work_and_duplicate_json_keys_without_latest_or_cross_call_cache() {
    let fixture = Fixture::new();
    fixture.evidence("latest", &payload(SESSION));
    assert_eq!(menu(fixture.legacy()), Some(vec![]));
    let path = fixture.evidence(RUN, &payload(SESSION));
    assert_eq!(
        menu(fixture.legacy()),
        Some(vec![(MENU.into(), SESSION.into())])
    );
    let wrong =
        json!({"work":{"id":"wrong"},"runtime_session":{"runtime":"codex","session_id":SESSION}})
            .to_string();
    fs::write(&path, wrong).unwrap();
    assert_eq!(menu(fixture.legacy()), Some(vec![]));
    let duplicate = format!(
        r#"{{"work":{{"id":"wrong"}},"work":{{"id":"{WORK}"}},"runtime_session":{{"runtime":"agy"}},"runtime_session":{{"runtime":"codex","session_id":"{MAX_SESSION}"}}}}"#
    );
    fs::write(&path, &duplicate).unwrap();
    assert_eq!(
        menu(fixture.legacy()),
        Some(vec![(MENU.into(), MAX_SESSION.into())])
    );
    assert_eq!(fs::read(&path).unwrap(), duplicate.as_bytes());
}

#[test]
fn evidence_failures_are_unbound_and_unsupported_parser_inputs_decline() {
    let fixture = Fixture::new();
    for contents in [
        b"{".as_slice(),
        b"\xff",
        b"null",
        b"[]",
        br#"{"work":null}"#,
        br#"{"work":{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"runtime_session":[1]}"#,
    ] {
        let path = fixture.evidence(RUN, contents);
        assert_eq!(menu(fixture.legacy()), Some(vec![]));
        assert_eq!(fs::read(path).unwrap(), contents);
    }
    fixture.evidence(RUN, br#"{"unused":"\ud800"}"#);
    assert!(menu(fixture.legacy()).is_none());
    let deep = "[".repeat(129) + "0" + &"]".repeat(129);
    fixture.evidence(RUN, deep.as_bytes());
    assert!(menu(fixture.legacy()).is_none());
    let mut removed = fixture.legacy();
    set(
        &mut removed,
        "project",
        json!(["text", fixture.root.join("removed").to_str().unwrap()]),
    );
    set(&mut removed, "work_id", json!(["blob", "ff"]));
    set(&mut removed, "summary", json!(["blob", "ff"]));
    assert_eq!(menu(removed), Some(vec![]));
}

#[test]
fn menu_filters_before_rendering_and_retains_dense_order_and_unicode_date_slices() {
    let mut invalid = card("--last");
    for name in ["summary", "state", "updated_at"] {
        set(&mut invalid, name, json!(["integer", 1]));
    }
    let first = card(SESSION);
    let mut second = card(MAX_SESSION);
    set(&mut second, "summary", json!(["text", "second"]));
    set(&mut second, "state", json!(["text", "active"]));
    assert_eq!(
        CardResume::menu(&json!([invalid, first, second])),
        Some(vec![
            (MENU.into(), SESSION.into()),
            ("2. second [active, 😀123456789]".into(), MAX_SESSION.into())
        ])
    );
    let mut reached = card(SESSION);
    set(&mut reached, "updated_at", json!(["integer", 1]));
    assert!(menu(reached).is_none());
}

#[test]
fn unsafe_evidence_paths_and_fifo_decline_before_menu_without_reading_a_stream() {
    let fixture = Fixture::new();
    let path = fixture.evidence(RUN, &payload(SESSION));
    let before = fs::read(&path).unwrap();
    let alias = fixture.root.join("alias");
    symlink(&fixture.project, &alias).unwrap();
    let mut aliased = fixture.legacy();
    set(
        &mut aliased,
        "project",
        json!(["text", alias.to_str().unwrap()]),
    );
    assert!(menu(aliased).is_none());
    let target = fixture.root.join("target.json");
    fs::write(&target, &before).unwrap();
    fs::remove_file(&path).unwrap();
    symlink(&target, &path).unwrap();
    assert!(menu(fixture.legacy()).is_none());
    fs::remove_file(&path).unwrap();
    let name = CString::new(path.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    assert!(menu(fixture.legacy()).is_none());
    let mut explicit = fixture.legacy();
    set(&mut explicit, "runtime", json!(["text", "codex"]));
    set(&mut explicit, "session_id", json!(["text", "--last"]));
    assert_eq!(
        menu(explicit),
        Some(vec![]),
        "invalid explicit binding must not open the FIFO"
    );
    assert_eq!(fs::read(target).unwrap(), before);
}

#[test]
fn oversized_evidence_and_reached_nontext_legacy_fields_decline() {
    let fixture = Fixture::new();
    let path = fixture.evidence(RUN, b"");
    let file = fs::OpenOptions::new().write(true).open(&path).unwrap();
    file.set_len(64 * 1024 * 1024 + 1).unwrap();
    assert!(menu(fixture.legacy()).is_none());
    assert_eq!(file.metadata().unwrap().len(), 64 * 1024 * 1024 + 1);
    for (name, cell) in [
        ("run_id", json!(["integer", 1])),
        ("project", json!(["blob", ""])),
    ] {
        let mut row = fixture.legacy();
        set(&mut row, name, cell);
        assert!(menu(row).is_none());
    }
    for project in [
        "nul\0path".to_owned(),
        format!("/{}", fixture.project.display()),
    ] {
        let mut row = fixture.legacy();
        set(&mut row, "project", json!(["text", project]));
        assert!(menu(row).is_none());
    }
}
