use super::*;

fn args(values: &[&str]) -> Vec<OsString> {
    values.iter().map(OsString::from).collect()
}

#[test]
fn canonical_generated_defaults_and_state_dependencies_are_complete() {
    let policy = RegistryRead::retention_policy().unwrap();
    assert_eq!(policy["keep"], json!(10));
    assert_eq!(policy["abandoned_after_seconds"], json!(30 * 24 * 60 * 60));
    assert_eq!(policy["orphan_after_seconds"], json!(14 * 24 * 60 * 60));
    for state in [
        "running",
        "claiming",
        "completed",
        "cancelled",
        "reconcile_required",
    ] {
        assert!(policy["run_states"]
            .as_array()
            .unwrap()
            .contains(&json!(state)));
    }
    let options = RegistryRead::retention_report_args(&[], &policy).unwrap();
    assert_eq!(options["keep"], policy["keep"]);
    assert_eq!(options["project"], json!(std::env::current_dir().unwrap()));
}

#[test]
fn ordinary_split_equal_repeated_signed_options_match_argparse() {
    let policy = RegistryRead::retention_policy().unwrap();
    let options = RegistryRead::retention_report_args(
        &args(&[
            "--keep",
            "8",
            "--keep=+2",
            "--project=/ordinary/project",
            "--abandoned-after-seconds",
            "-1",
            "--orphan-after-seconds=60",
        ]),
        &policy,
    )
    .unwrap();
    assert_eq!(
        options,
        json!({"project":"/ordinary/project", "keep":2,
        "abandoned_after_seconds":0, "orphan_after_seconds":60})
    );
}

#[test]
fn unsupported_profiles_decline_including_every_apply_form() {
    let policy = RegistryRead::retention_policy().unwrap();
    for values in [
        vec!["--apply"],
        vec!["--apply=true"],
        vec!["--app"],
        vec!["--help"],
        vec!["--keep"],
        vec!["--keep", "1_0"],
        vec!["--keep= 1"],
        vec!["--keep=１２"],
        vec!["--keep=9223372036854775808"],
        vec!["--project", "relative"],
        vec!["--keep=1", "extra"],
        vec!["--unknown=value"],
        vec!["--"],
    ] {
        assert!(
            RegistryRead::retention_report_args(&args(&values), &policy).is_none(),
            "{values:?}"
        );
    }
}

#[test]
fn unsupported_metadata_never_admits_a_report() {
    let policy = RegistryRead::retention_policy().unwrap();
    for (name, value) in [
        ("schema_version", json!(2)),
        ("run_id_length", json!(16)),
        ("registry_schema_version", json!(2)),
        ("runs_dir", json!(null)),
        ("state_dir", json!("../outside")),
        ("keep", json!(true)),
        ("run_states", json!([null])),
        ("finished_phases", json!({})),
    ] {
        let mut changed = policy.clone();
        changed[name] = value;
        assert!(
            !RegistryRead::retention_policy_supported(&changed),
            "{name}"
        );
    }
}

#[test]
fn raw_non_utf8_arguments_decline() {
    use std::os::unix::ffi::OsStringExt;
    let policy = RegistryRead::retention_policy().unwrap();
    assert!(RegistryRead::retention_report_args(
        &[
            OsString::from("--project"),
            OsString::from_vec(vec![b'/', 0xff]),
        ],
        &policy
    )
    .is_none());
}
