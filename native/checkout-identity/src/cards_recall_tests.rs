use super::CardRecall;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    os::unix::fs::symlink,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "moru-cards-recall-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path.canonicalize().unwrap())
    }
    fn project(&self, name: &str, registry: Option<&[u8]>) -> PathBuf {
        let path = self.0.join(name);
        fs::create_dir(&path).unwrap();
        if let Some(bytes) = registry {
            fs::create_dir(path.join(".moru")).unwrap();
            fs::write(path.join(".moru/run-registry.json"), bytes).unwrap();
        }
        path
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn card(id: &str, project: &Path) -> Value {
    json!([
        ["work_id", ["text", id]],
        ["project", ["text", project.to_str().unwrap()]],
        ["run_id", ["text", "run"]],
        ["command", ["text", "feature"]],
        ["updated_at", ["text", "😀123456789X"]],
        ["summary", ["text", "summary"]]
    ])
}
fn set(card: &mut Value, field: &str, cell: Value) {
    let pair = card
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|pair| pair[0] == field)
        .unwrap();
    pair[1] = cell;
}
const LIVE: &[u8] = br#"{"runs":[{"run_id":"run","state":"running"}]}"#;
const HEADER: &str = "Open work cards in this repository (reference only; close finished ones with `work-cards close <work id>`):";

#[test]
fn selection_checks_twenty_others_renders_three_and_counts_unused_cards() {
    let fixture = Fixture::new();
    let project = fixture.project("project", Some(LIVE));
    let mut current = card("current", &project);
    set(&mut current, "project", json!(["blob", "ff"]));
    let mut cards = vec![current];
    for index in 0..23 {
        let mut row = card(&format!("work-{index}"), &project);
        set(
            &mut row,
            "summary",
            json!(["text", format!("summary-{index}")]),
        );
        if index >= 20 {
            set(&mut row, "project", json!(["integer", 7]));
            set(&mut row, "run_id", json!(["blob", "ff"]));
        }
        if index >= 3 {
            for field in ["command", "updated_at", "summary"] {
                set(&mut row, field, json!(["blob", "ff"]));
            }
        }
        cards.push(row);
    }
    let before = fs::read(project.join(".moru/run-registry.json")).unwrap();
    let result = CardRecall::evaluate(&Value::Array(cards), "current").unwrap();
    assert_eq!(
        result["lines"],
        json!([
            HEADER,
            "- work-0 [feature, 😀123456789] summary-0",
            "- work-1 [feature, 😀123456789] summary-1",
            "- work-2 [feature, 😀123456789] summary-2",
            "- 20 more: `work-cards list`"
        ])
    );
    assert_eq!(result["stale"], json!([]));
    assert_eq!(
        before,
        fs::read(project.join(".moru/run-registry.json")).unwrap()
    );
}

#[test]
fn stale_order_and_only_the_two_settled_registry_states_are_preserved() {
    let fixture = Fixture::new();
    let project = fixture.project(
        "project",
        Some(
            br#"{"runs":[
        {"run_id":"completed","state":"completed"},{"run_id":"cancelled","state":"cancelled"},
        {"run_id":"failed","state":"failed"},{"run_id":"future","state":"future-state"}]}"#,
        ),
    );
    let mut cards = Vec::new();
    for id in ["completed", "absent", "cancelled", "failed", "future"] {
        let mut row = card(id, &project);
        set(&mut row, "run_id", json!(["text", id]));
        cards.push(row);
    }
    let mut gone = card("gone", &fixture.0.join("missing"));
    set(&mut gone, "run_id", json!(["integer", 42]));
    set(&mut gone, "summary", json!(["blob", "ff"]));
    cards.push(gone);
    let result = CardRecall::evaluate(&Value::Array(cards), "").unwrap();
    assert_eq!(
        result["stale"],
        json!([
            ["completed", "done"],
            ["absent", "cancelled"],
            ["cancelled", "cancelled"],
            ["gone", "cancelled"]
        ])
    );
    assert_eq!(
        result["lines"],
        json!([
            HEADER,
            "- failed [feature, 😀123456789] summary",
            "- future [feature, 😀123456789] summary"
        ])
    );
}

#[test]
fn missing_invalid_and_noniterated_registry_shapes_are_empty() {
    let fixture = Fixture::new();
    for (index, contents) in [
        None,
        Some(&b"\xff"[..]),
        Some(&b"{"[..]),
        Some(&b"null"[..]),
        Some(&br#"{"runs":"abc"}"#[..]),
        Some(&br#"{"runs":{"run":{"state":"running"}}}"#[..]),
    ]
    .into_iter()
    .enumerate()
    {
        let project = fixture.project(&format!("project-{index}"), contents);
        assert_eq!(
            CardRecall::evaluate(&json!([card("work", &project)]), ""),
            Some(json!({"lines":[],"stale":[["work","cancelled"]]}))
        );
    }
}

#[test]
fn unsupported_registry_iteration_and_lossless_parser_boundaries_decline() {
    let fixture = Fixture::new();
    for (index, contents) in [
        br#"{"runs":null}"#.as_slice(),
        br#"{"runs":true}"#,
        br#"{"runs":17}"#,
        br#"{"runs":[{"run_id":"run","state":"\ud800"}]}"#,
    ]
    .into_iter()
    .enumerate()
    {
        let project = fixture.project(&format!("project-{index}"), Some(contents));
        assert!(CardRecall::evaluate(&json!([card("work", &project)]), "").is_none());
    }
    let deep = "[".repeat(129) + "0" + &"]".repeat(129);
    let project = fixture.project("deep", Some(deep.as_bytes()));
    assert!(CardRecall::evaluate(&json!([card("work", &project)]), "").is_none());
}

#[test]
fn registry_state_coercion_ignores_nonobjects_and_last_duplicate_wins() {
    let fixture = Fixture::new();
    let project = fixture.project("project",Some(br#"{"runs":[null,17,"ignored",{"run_id":3,"state":"running"},
        {"run_id":"run","state":"completed"},{"run_id":"run","state":[true]},
        {"run_id":"zero","state":0},{"run_id":"false","state":false},{"run_id":"null","state":null},
        {"run_id":"emptylist","state":[]},{"run_id":"emptydict","state":{}},
        {"run_id":"true","state":true},{"run_id":"number","state":1.5},{"run_id":"nan","state":NaN}]}"#));
    let cards = [
        "run",
        "zero",
        "false",
        "null",
        "emptylist",
        "emptydict",
        "true",
        "number",
        "nan",
    ]
    .iter()
    .map(|id| {
        let mut row = card(id, &project);
        set(&mut row, "run_id", json!(["text", id]));
        row
    })
    .collect();
    let result = CardRecall::evaluate(&Value::Array(cards), "").unwrap();
    assert_eq!(
        result["stale"],
        json!([
            ["zero", "cancelled"],
            ["false", "cancelled"],
            ["null", "cancelled"],
            ["emptylist", "cancelled"],
            ["emptydict", "cancelled"]
        ])
    );
    assert_eq!(
        result["lines"],
        json!([
            HEADER,
            "- run [feature, 😀123456789] summary",
            "- true [feature, 😀123456789] summary",
            "- number [feature, 😀123456789] summary",
            "- 1 more: `work-cards list`"
        ])
    );
}

#[test]
fn run_id_fallbacks_and_registry_cache_lifetime_match_the_invocation() {
    let fixture = Fixture::new();
    let project = fixture.project(
        "project",
        Some(
            br#"{"runs":[{"run_id":"a","state":"running"},
        {"run_id":"b","state":"running"},{"run_id":"c","state":"running"}]}"#,
        ),
    );
    let mut a = card("a", &project);
    set(&mut a, "run_id", json!(["text", ""]));
    let mut b = card("b", &project);
    set(&mut b, "run_id", json!(["null"]));
    let mut c = card("c", &project);
    c.as_array_mut().unwrap().retain(|pair| pair[0] != "run_id");
    let snapshot = json!([a, b, c]);
    assert_eq!(
        CardRecall::evaluate(&snapshot, "").unwrap()["stale"],
        json!([])
    );
    let mut cache = HashMap::new();
    assert_eq!(
        CardRecall::registry(&project, &mut cache)
            .unwrap()
            .get("a")
            .unwrap(),
        "running"
    );
    let changed = br#"{"runs":[{"run_id":"a","state":"completed"},{"run_id":"b","state":"completed"},{"run_id":"c","state":"completed"}]}"#;
    fs::write(project.join(".moru/run-registry.json"), changed).unwrap();
    assert_eq!(
        CardRecall::registry(&project, &mut cache)
            .unwrap()
            .get("a")
            .unwrap(),
        "running"
    );
    assert_eq!(
        CardRecall::evaluate(&snapshot, "").unwrap(),
        json!({"lines":[],"stale":[["a","done"],["b","done"],["c","done"]]})
    );
    assert_eq!(
        fs::read(project.join(".moru/run-registry.json")).unwrap(),
        changed
    );
}

#[test]
fn registry_cache_keys_drop_dots_without_resolving_parents_roots_or_aliases() {
    let known = |state: &str| HashMap::from([("run".to_owned(), state.to_owned())]);
    let mut cache = HashMap::from([
        (PathBuf::from("relative"), known("relative")),
        (PathBuf::from("alias"), known("alias")),
        (PathBuf::from("relative/../alias"), known("parent")),
        (PathBuf::new(), known("empty")),
        (PathBuf::from("."), known("unnormalized dot")),
        (PathBuf::from("/"), known("root")),
    ]);
    for (path, expected) in [
        ("./relative", "relative"),
        ("relative", "relative"),
        ("./alias", "alias"),
        ("./relative/../alias", "parent"),
        ("", "empty"),
        (".", "empty"),
        ("./", "empty"),
        ("/./", "root"),
    ] {
        assert_eq!(
            CardRecall::registry(Path::new(path), &mut cache)
                .unwrap()
                .get("run")
                .unwrap(),
            expected
        );
    }
    assert_eq!(
        cache.len(),
        6,
        "every lookup must reuse a seeded cache entry"
    );
}

#[test]
fn symlinks_and_oversized_registry_files_decline_without_consumption() {
    let fixture = Fixture::new();
    let project = fixture.project("project", Some(LIVE));
    let alias = fixture.0.join("alias");
    symlink(&project, &alias).unwrap();
    assert!(CardRecall::evaluate(&json!([card("work", &alias)]), "").is_none());
    let linked = fixture.project("linked", None);
    fs::create_dir(linked.join(".moru")).unwrap();
    symlink(
        project.join(".moru/run-registry.json"),
        linked.join(".moru/run-registry.json"),
    )
    .unwrap();
    assert!(CardRecall::evaluate(&json!([card("work", &linked)]), "").is_none());
    let huge = fixture.project("huge", Some(b""));
    let file = fs::OpenOptions::new()
        .write(true)
        .open(huge.join(".moru/run-registry.json"))
        .unwrap();
    file.set_len(64 * 1024 * 1024 + 1).unwrap();
    assert!(CardRecall::evaluate(&json!([card("work", &huge)]), "").is_none());
    assert_eq!(file.metadata().unwrap().len(), 64 * 1024 * 1024 + 1);
    assert_eq!(
        fs::read(project.join(".moru/run-registry.json")).unwrap(),
        LIVE
    );
}

#[test]
fn missing_non_directory_and_unsafe_project_paths_follow_explicit_boundaries() {
    let fixture = Fixture::new();
    let project = fixture.project("project", Some(LIVE));
    for path in ["nul\0path".to_owned(), format!("/{}", project.display())] {
        let mut row = card("work", &project);
        set(&mut row, "project", json!(["text", path]));
        assert!(CardRecall::evaluate(&json!([row]), "").is_none());
    }
    let file = fixture.0.join("file");
    fs::write(&file, b"owned").unwrap();
    let looping = fixture.0.join("loop");
    symlink("loop", &looping).unwrap();
    for path in [fixture.0.join("missing"), file.join("child"), file, looping] {
        let mut row = card("work", &path);
        set(&mut row, "run_id", json!(["integer", 7]));
        assert_eq!(
            CardRecall::evaluate(&json!([row]), ""),
            Some(json!({"lines":[],"stale":[["work","cancelled"]]}))
        );
    }
    let mut used = card("work", &project);
    set(&mut used, "command", json!(["integer", 7]));
    assert!(CardRecall::evaluate(&json!([used]), "").is_none());
}
