use super::*;
use std::{
    fs::{File, FileTimes},
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
    time::Duration,
};

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "moru-retention-report-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path.canonicalize().unwrap())
    }
    fn directory(&self) -> PathBuf {
        self.0.join(".moru/runs")
    }
    fn run(&self, number: usize, packet: &[u8], seconds: u64) -> String {
        let name = format!("{number:032x}");
        let path = self.directory().join(&name);
        fs::create_dir_all(&path).unwrap();
        fs::write(path.join("continuation.json"), packet).unwrap();
        File::open(path)
            .unwrap()
            .set_times(FileTimes::new().set_modified(UNIX_EPOCH + Duration::from_secs(seconds)))
            .unwrap();
        name
    }
    fn options(&self) -> Value {
        json!({"project":self.0, "keep":1, "abandoned_after_seconds":60, "orphan_after_seconds":60})
    }
    fn report(&self) -> Option<String> {
        RegistryRead::retention_report(&self.options(), &RegistryRead::retention_policy().unwrap())
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn absent_file_and_empty_run_directories_have_exact_report_text() {
    let f = Fixture::new();
    let absent = format!("no run directory at {}\n", f.directory().display());
    assert_eq!(f.report(), Some(absent.clone()));
    fs::create_dir(f.0.join(".moru")).unwrap();
    fs::write(f.directory(), b"file").unwrap();
    assert_eq!(f.report(), Some(absent));
    fs::remove_file(f.directory()).unwrap();
    fs::create_dir(f.directory()).unwrap();
    assert_eq!(f.report().unwrap(), format!("runs: {}\nfinished: 0  unfinished: 0  abandoned: 0  orphaned: 0\nkeeping the newest 0 finished; removable: 0\nnothing to remove\n", f.directory().display()));
    assert_eq!(
        fs::read_dir(f.0.join(".moru")).unwrap().count(),
        1,
        "report creates no locks or registry"
    );
}

#[test]
fn report_reuses_plan_order_phase_truthiness_and_byte_totals() {
    let f = Fixture::new();
    f.run(1, br#"{"phase":"done"}"#, 20);
    f.run(2, br#"{"phase":"done"}"#, 10);
    f.run(3, br#"{"phase":true}"#, 1);
    let unreadable = f.run(4, b"{", 1);
    fs::create_dir(f.directory().join("human")).unwrap();
    fs::write(f.directory().join("human/note"), b"abc").unwrap();
    let output = f.report().unwrap();
    assert_eq!(output, format!("runs: {}\nfinished: 2  unfinished: 1  abandoned: 1  orphaned: 0\nnot named like a run id, never removed: 1 (3 bytes)\nkeeping the newest 1 finished; removable: 2\nunfinished runs are kept while they can still be resumed:\n    {unreadable}  phase=unreadable\nbytes to free: 30\nreport only; pass --apply to remove them\n", f.directory().display()));
    assert_eq!(fs::read_dir(f.directory()).unwrap().count(), 5);
    assert!(!f.0.join(".moru/run-registry.json").exists());
}

#[test]
fn registry_holding_settled_orphan_and_uncertain_states_are_shared() {
    let f = Fixture::new();
    let held = f.run(1, br#"{"phase":"done"}"#, 1);
    let settled = f.run(2, br#"{"phase":"testing"}"#, 2);
    f.run(3, br#"{"phase":"done"}"#, 3);
    let path = f.0.join(".moru/run-registry.json");
    fs::write(
        &path,
        json!({"schema_version":1, "runs":[
        {"run_id":held,"state":"running"},{"run_id":settled,"state":"completed"}]})
        .to_string(),
    )
    .unwrap();
    let output = f.report().unwrap();
    assert!(output.contains("finished: 1  unfinished: 1  abandoned: 0  orphaned: 1\n"));
    assert!(output.contains(&format!("    {held}  phase=done\n")));
    fs::write(&path, r#"{"schema_version":2,"runs":[]}"#).unwrap();
    let output = f.report().unwrap();
    assert!(output.contains("finished: 0  unfinished: 3  abandoned: 0  orphaned: 0\n"));
    assert!(output.ends_with("nothing to remove\n"));
}

#[test]
fn unfinished_display_limit_reads_only_the_first_five_phases() {
    let f = Fixture::new();
    let mut runs = Vec::new();
    for number in 1..=7 {
        let name = f.run(number, br#"{"phase":"testing"}"#, 1);
        runs.push(json!({"run_id":name,"state":"running"}));
    }
    fs::write(
        f.0.join(".moru/run-registry.json"),
        json!({"schema_version":1,"runs":runs}).to_string(),
    )
    .unwrap();
    fs::write(
        f.directory().join(format!("{:032x}/continuation.json", 6)),
        br#"{"phase":"\ud800"}"#,
    )
    .unwrap();
    let output = f.report().unwrap();
    assert_eq!(output.matches("phase=testing").count(), 5);
    assert!(output.contains("    ... and 2 more\n"));
}

#[test]
fn unsupported_inputs_defer_without_partial_reports() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    let name = f.run(1, br#"{"phase":"done"}"#, 1);
    let registry = f.0.join(".moru/run-registry.json");
    for bytes in [
        b"{".as_slice(),
        br#"{"schema_version":1,"runs":[],"x":"\ud800"}"#,
    ] {
        fs::write(&registry, bytes).unwrap();
        assert!(f.report().is_none());
    }
    fs::remove_file(registry).unwrap();
    fs::remove_file(f.directory().join(&name).join("continuation.json")).unwrap();
    symlink("absent", f.directory().join(name).join("continuation.json")).unwrap();
    assert!(f.report().is_none());
    let mut raw = f.options();
    raw["project"] = json!(format!("{}/.", f.0.display()));
    assert!(
        RegistryRead::retention_report(&raw, &RegistryRead::retention_policy().unwrap()).is_none()
    );
}

#[test]
fn state_directory_symlinks_preserve_original_path_behavior_via_deferral() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    fs::create_dir(f.0.join("elsewhere")).unwrap();
    symlink("elsewhere", f.0.join(".moru")).unwrap();
    assert!(f.report().is_none());
}
