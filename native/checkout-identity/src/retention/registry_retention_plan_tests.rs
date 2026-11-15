use super::*;
use std::{
    fs::{File, FileTimes},
    os::unix::fs::symlink,
    sync::atomic::{AtomicUsize, Ordering},
    time::Duration,
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "moru-retention-plan-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path.canonicalize().unwrap())
    }
    fn run(&self, number: usize, packet: &[u8], seconds: u64) -> String {
        let name = format!("{number:032x}");
        let path = self.0.join(&name);
        fs::create_dir(&path).unwrap();
        fs::write(path.join("continuation.json"), packet).unwrap();
        Self::touch(&path, seconds);
        name
    }
    fn touch(path: &Path, seconds: u64) {
        File::open(path)
            .unwrap()
            .set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(seconds)))
            .unwrap();
    }
    fn payload(&self) -> Value {
        json!({"directory":self.0,"registry_states":null,"registry_uncertain":false,
            "protected":[],"cutoff":10.0,"orphan_cutoff":10.0,"keep":0,
            "holding_states":["running","paused","resuming","claiming"],
            "settled_states":["completed","cancelled"],"finished_phases":["done"],
            "int_digits":option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
                .unwrap_or("0").parse::<u64>().unwrap()})
    }
    fn entries(&self, names: &[String]) -> Vec<(String, PathBuf)> {
        names
            .iter()
            .map(|name| (name.clone(), self.0.join(name)))
            .collect()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn finished_ties_keep_and_removal_groups_preserve_reference_order() {
    let f = Fixture::new();
    let a = f.run(1, br#"{"phase":"done"}"#, 20);
    let b = f.run(2, br#"{"phase":"done"}"#, 20);
    let c = f.run(3, br#"{"phase":"testing"}"#, 1);
    let d = f.run(4, br#"{"phase":"testing"}"#, 1);
    let e = f.run(5, br#"{"phase":"done"}"#, 1);
    let recent = f.run(6, br#"{"phase":"done"}"#, 10);
    let mut p = f.payload();
    p["keep"] = json!(1);
    p["registry_states"] = json!({a.clone():"completed",b.clone():"cancelled",
        c.clone():"completed",d.clone():"other"});
    let result = RegistryRead::inspect("retention-plan", &p).unwrap();
    assert_eq!(result["finished"], json!([a, b, c]));
    assert_eq!(result["kept"], json!([a]));
    assert_eq!(result["abandoned"], json!([d]));
    assert_eq!(result["orphaned"], json!([e, recent]));
    assert_eq!(result["removable"], json!([b, c, d, e]));
    let pairs = result["identities"].as_array().unwrap();
    assert_eq!(
        pairs.iter().map(|pair| pair[0].clone()).collect::<Vec<_>>(),
        result["removable"].as_array().unwrap().clone()
    );
    for pair in pairs {
        assert_eq!(
            pair[1],
            RegistryRead::retention_identities(
                &json!({"paths":[f.0.join(pair[0].as_str().unwrap())]})
            )
            .unwrap()[0]
        );
    }
}

#[test]
fn holding_protected_uncertain_and_orphan_paths_skip_phase_reads() {
    let f = Fixture::new();
    let a = f.run(1, br#"{"phase":"\ud800"}"#, 1);
    let b = f.run(2, br#"{"phase":"\ud800"}"#, 1);
    let c = f.run(3, br#"{"phase":"\ud800"}"#, 10);
    let d = f.run(4, br#"{"phase":"\ud800"}"#, 1);
    let mut p = f.payload();
    p["registry_states"] = json!({a.clone():"running",b.clone():"other"});
    p["protected"] = json!([b]);
    let result = RegistryRead::retention_plan(&p).unwrap();
    assert_eq!(result["unfinished"], json!([a, b]));
    assert_eq!(result["orphaned"], json!([c, d]));
    assert_eq!(result["removable"], json!([d]));
    p["registry_uncertain"] = json!(true);
    assert_eq!(
        RegistryRead::retention_plan(&p).unwrap()["unfinished"],
        json!([a, b, c, d])
    );
    p["registry_uncertain"] = json!(false);
    p["registry_states"] = json!({a:"completed"});
    assert!(
        RegistryRead::retention_plan(&p).is_none(),
        "settled still reads phase first"
    );
}

#[test]
fn phase_errors_and_python_truthiness_are_distinct_from_unsupported_inputs() {
    let f = Fixture::new();
    for (packet, expected) in [
        ("{", ""),
        ("[]", ""),
        ("null", ""),
        (r#"{"phase":null}"#, ""),
        (r#"{"phase":0}"#, ""),
        (r#"{"phase":false}"#, ""),
        (r#"{"phase":[]}"#, ""),
        (r#"{"phase":{}}"#, ""),
        (r#"{"phase":true}"#, "True"),
        (r#"{"phase":[false]}"#, "[False]"),
        (r#"{"phase":{"a":1}}"#, "{'a': 1}"),
        (r#"{"phase":NaN}"#, "nan"),
        (r#"{"phase":Infinity}"#, "inf"),
        (r#"{"phase":"done","phase":"testing"}"#, "testing"),
    ] {
        fs::write(f.0.join("continuation.json"), packet).unwrap();
        assert_eq!(
            phase(&f.0, &mut (8 * 1024 * 1024)),
            Some(expected.into()),
            "{packet}"
        );
    }
    fs::write(f.0.join("continuation.json"), [0xff]).unwrap();
    assert_eq!(phase(&f.0, &mut 100), Some(String::new()));
    fs::remove_file(f.0.join("continuation.json")).unwrap();
    assert_eq!(phase(&f.0, &mut 100), Some(String::new()));
    fs::create_dir(f.0.join("continuation.json")).unwrap();
    assert_eq!(phase(&f.0, &mut 100), Some(String::new()));
    fs::remove_dir(f.0.join("continuation.json")).unwrap();
    for packet in [r#"{"phase":"\ud800"}"#.to_owned(), "[".repeat(130)] {
        fs::write(f.0.join("continuation.json"), packet).unwrap();
        assert!(phase(&f.0, &mut 1000).is_none());
    }
}

#[test]
fn integer_digit_limit_declines_even_for_ignored_values() {
    let f = Fixture::new();
    let limit = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")
        .unwrap_or("0")
        .parse::<usize>()
        .unwrap();
    let digits = if limit == 0 { 5000 } else { limit + 1 };
    let packet = format!(r#"{{"phase":"done","ignored":{}}}"#, "9".repeat(digits));
    fs::write(f.0.join("continuation.json"), packet).unwrap();
    let value = phase(&f.0, &mut (8 * 1024 * 1024));
    if limit == 0 {
        assert_eq!(value, Some("done".into()));
    } else {
        assert!(value.is_none());
    }
}

#[test]
fn second_phase_observation_can_change_truthiness_without_reclassifying_finished() {
    let f = Fixture::new();
    let name = f.run(1, b"{}", 1);
    let p = f.payload();
    let prepared = Prepared::read(&p).unwrap();
    for (second, abandoned) in [("", false), ("testing", true), ("done", true)] {
        let mut calls = 0;
        let result = classify(&prepared, f.entries(&[name.clone()]), |_| {
            calls += 1;
            Some(if calls == 1 { "testing" } else { second }.into())
        })
        .unwrap();
        assert_eq!(calls, 2);
        assert!(result.finished.is_empty());
        assert_eq!(!result.abandoned.is_empty(), abandoned);
        assert_eq!(!result.unfinished.is_empty(), !abandoned);
    }
}

#[test]
fn touched_stat_failure_uses_fresh_time_and_finished_sort_failure_declines() {
    let f = Fixture::new();
    let name = f.run(1, b"{}", 1);
    let p = f.payload();
    let prepared = Prepared::read(&p).unwrap();
    let mut calls = 0;
    let result = classify(&prepared, f.entries(&[name.clone()]), |path| {
        calls += 1;
        if calls == 2 {
            fs::remove_dir_all(path).unwrap();
        }
        Some("testing".into())
    })
    .unwrap();
    assert_eq!(result.unfinished, vec![name.clone()]);
    let name = f.run(1, b"{}", 1);
    let result = classify(&prepared, f.entries(&[name.clone()]), |_| {
        Some("done".into())
    })
    .unwrap();
    fs::remove_dir_all(f.0.join(name)).unwrap();
    assert!(RegistryRead::project_plan(&prepared, result).is_none());
}

#[test]
fn finished_sort_uses_fresh_mtime_after_classification() {
    let f = Fixture::new();
    let a = f.run(1, b"{}", 1);
    let b = f.run(2, b"{}", 2);
    let p = f.payload();
    let prepared = Prepared::read(&p).unwrap();
    let result = classify(&prepared, f.entries(&[a.clone(), b.clone()]), |_| {
        Some("done".into())
    })
    .unwrap();
    Fixture::touch(&f.0.join(&a), 3);
    assert_eq!(
        RegistryRead::project_plan(&prepared, result).unwrap()["finished"],
        json!([a, b])
    );
}

#[test]
fn symlinks_files_and_human_names_are_unclassified_and_identity_does_not_follow_links() {
    let f = Fixture::new();
    let a = f.run(1, br#"{"phase":"done"}"#, 1);
    let link = format!("{:032x}", 2);
    let broken = format!("{:032x}", 3);
    symlink(&a, f.0.join(&link)).unwrap();
    symlink("absent", f.0.join(&broken)).unwrap();
    fs::write(f.0.join(format!("{:032x}", 4)), b"file").unwrap();
    for name in ["human", "ABCDEF01234567890123456789012345", "한글"] {
        fs::create_dir(f.0.join(name)).unwrap();
    }
    symlink("../../absent", f.0.join(&a).join("broken")).unwrap();
    let result = RegistryRead::retention_plan(&f.payload()).unwrap();
    assert_eq!(result["removable"], json!([a]));
    assert_eq!(result["unclassified"].as_array().unwrap().len(), 6);
    assert_eq!(
        result["identities"][0][1]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row[0].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec![".", "broken", "continuation.json"]
    );
}

#[test]
fn unsupported_phase_files_decline_without_following_or_blocking() {
    let f = Fixture::new();
    let name = f.run(1, br#"{"phase":"done"}"#, 1);
    let packet = f.0.join(&name).join("continuation.json");
    fs::remove_file(&packet).unwrap();
    fs::write(f.0.join("packet"), br#"{"phase":"done"}"#).unwrap();
    symlink("../packet", &packet).unwrap();
    assert!(RegistryRead::retention_plan(&f.payload()).is_none());
    fs::remove_file(&packet).unwrap();
    let packet_c = std::ffi::CString::new(packet.to_str().unwrap()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(packet_c.as_ptr(), 0o600) }, 0);
    assert!(RegistryRead::retention_plan(&f.payload()).is_none());
}

#[test]
fn exact_abandoned_cutoff_keeps_truthy_packets() {
    let f = Fixture::new();
    let before = f.run(1, br#"{"phase":[true]}"#, 9);
    let exact = f.run(2, br#"{"phase":true}"#, 10);
    let result = RegistryRead::retention_plan(&f.payload()).unwrap();
    assert_eq!(result["abandoned"], json!([before]));
    assert_eq!(result["unfinished"], json!([exact]));
}

#[test]
fn request_shape_and_canonical_directory_are_strict() {
    let f = Fixture::new();
    let p = f.payload();
    assert_eq!(
        RegistryRead::retention_plan(&p).unwrap(),
        json!({
        "finished":[],"unfinished":[],"abandoned":[],"orphaned":[],
        "unclassified":[],"kept":[],"removable":[],"identities":[]})
    );
    for (key, value) in [
        ("extra", json!(0)),
        ("keep", json!(-1)),
        ("keep", json!(1.0)),
        ("keep", json!(true)),
        ("cutoff", json!("1")),
        ("orphan_cutoff", json!(false)),
        ("registry_states", json!({"a":false})),
        ("registry_uncertain", json!(0)),
        ("protected", json!([null])),
        ("finished_phases", json!([1])),
        ("holding_states", json!(null)),
        ("settled_states", json!("done")),
    ] {
        let mut bad = p.clone();
        bad[key] = value;
        assert!(RegistryRead::retention_plan(&bad).is_none(), "{key}");
    }
    let mut bad = p.clone();
    bad["int_digits"] = json!(p["int_digits"].as_u64().unwrap() + 1);
    assert!(RegistryRead::retention_plan(&bad).is_none());
    let mut bad = p.clone();
    bad.as_object_mut().unwrap().remove("keep");
    assert!(RegistryRead::retention_plan(&bad).is_none());
    for directory in [
        "relative".to_owned(),
        format!("{}/..", f.0.display()),
        format!("{}/missing", f.0.display()),
    ] {
        let mut bad = p.clone();
        bad["directory"] = json!(directory);
        assert!(RegistryRead::retention_plan(&bad).is_none());
    }
}

#[test]
fn packet_and_total_read_bounds_never_return_partial_phases() {
    let f = Fixture::new();
    let packet = f.0.join("continuation.json");
    fs::write(&packet, b"{}").unwrap();
    let mut remaining = 3;
    assert_eq!(phase(&f.0, &mut remaining), Some(String::new()));
    assert_eq!(remaining, 1);
    assert!(phase(&f.0, &mut remaining).is_none());
    fs::write(&packet, vec![b' '; 1024 * 1024 + 1]).unwrap();
    assert!(phase(&f.0, &mut (8 * 1024 * 1024)).is_none());
    fs::write(&packet, vec![b' '; 1024 * 1024]).unwrap();
    assert_eq!(phase(&f.0, &mut (8 * 1024 * 1024)), Some(String::new()));
}

#[test]
fn scan_and_removable_root_bounds_decline_the_whole_response() {
    let f = Fixture::new();
    for number in 0..257 {
        f.run(number, br#"{"phase":"done"}"#, 1);
    }
    assert!(RegistryRead::retention_plan(&f.payload()).is_none());
    let mut p = f.payload();
    p["keep"] = json!(1);
    assert_eq!(
        RegistryRead::retention_plan(&p).unwrap()["identities"]
            .as_array()
            .unwrap()
            .len(),
        256
    );
    p["keep"] = json!(257);
    for number in 257..4096 {
        fs::write(f.0.join(format!("human-{number}")), b"").unwrap();
    }
    assert!(RegistryRead::retention_plan(&p).is_some());
    fs::write(f.0.join("one-too-many"), b"").unwrap();
    assert!(RegistryRead::retention_plan(&p).is_none());
}

#[test]
fn identity_budget_is_shared_across_every_removable_root() {
    let f = Fixture::new();
    let a = f.run(1, br#"{"phase":"done"}"#, 1);
    let b = f.run(2, br#"{"phase":"done"}"#, 1);
    for number in 0..4092 {
        fs::write(f.0.join(&a).join(format!("child-{number}")), b"").unwrap();
    }
    let p = f.payload();
    let result = RegistryRead::retention_plan(&p).unwrap();
    assert_eq!(result["removable"], json!([a, b]));
    assert_eq!(
        result["identities"]
            .as_array()
            .unwrap()
            .iter()
            .map(|pair| pair[1].as_array().unwrap().len())
            .sum::<usize>(),
        4096
    );
    fs::write(f.0.join(&b).join("extra"), b"").unwrap();
    assert!(RegistryRead::retention_plan(&p).is_none());
}
