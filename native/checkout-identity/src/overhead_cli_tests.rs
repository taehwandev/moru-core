use super::*;
fn parse(args: &[&str]) -> Option<OverheadCli> {
    OverheadCli::parse(
        Path::new("/core"),
        Path::new("/home/user"),
        &args.iter().map(OsString::from).collect::<Vec<_>>(),
    )
}
#[test]
fn defaults_and_repeated_values_keep_argument_contract() {
    let args = parse(&[]).unwrap();
    assert_eq!((args.days, args.min_turns, args.exit), (30, 1, None));
    assert_eq!(args.projects_dir, "/home/user/.claude/projects");
    assert_eq!(args.timings, "/home/user/.moru/timings.jsonl");
    assert_eq!(args.moru_root, "/core");
    let args = parse(&[
        "--days=2",
        "--d",
        "-3",
        "--alias-root",
        "a",
        "--alias",
        "b",
        "--exclude-session=skip",
        "--include-subagents",
        "--min-turns=-10",
        "--out=",
        "--md=x",
    ])
    .unwrap();
    assert_eq!((args.days, args.min_turns), (-3, -10));
    assert_eq!(args.alias_root, ["a", "b"]);
    assert_eq!(args.exclude_session, ["skip"]);
    assert_eq!(args.out, Some(String::new()));
    assert!(args.include_subagents);
}
#[test]
fn integer_coercion_preserves_python_unicode_and_separators() {
    for (text, expected) in [
        ("١_٢", 12),
        (" +００１ ", 1),
        ("\u{85}-2\u{85}", -2),
        ("-0", 0),
    ] {
        assert_eq!(OverheadCli::integer(text), Some(Ok(expected)));
    }
    for text in ["", "_1", "1_", "1__2", "+ 1", "1.0", "\u{1c}1", "²"] {
        assert_eq!(OverheadCli::integer(text), Some(Err(())), "{text:?}");
    }
    assert_eq!(OverheadCli::integer("9223372036854775808"), None);
}
#[test]
fn ambiguous_names_and_negative_numbers_match_builder_profile() {
    assert_eq!(
        OverheadCli::name("--m"),
        Err("ambiguous option: --m could match --moru-root, --min-turns, --md".into())
    );
    assert!(!OverheadCli::option("-1\n"));
    assert!(!OverheadCli::option("-.5"));
    assert_eq!(
        OverheadCli::option("-1_0"),
        OverheadCli::NEGATIVE != "prefix"
    );
    assert!(!OverheadCli::option("-x y"));
    assert_eq!(
        OverheadCli::option("-1x"),
        OverheadCli::NEGATIVE != "prefix"
    );
}
#[test]
fn malformed_and_terminator_arguments_return_argparse_exit() {
    for args in [
        &["--"][..],
        &["--days"][..],
        &["--days", "x"][..],
        &["--include-subagents=x"][..],
    ] {
        assert_eq!(parse(args).unwrap().exit, Some(2));
    }
}
#[test]
fn help_layout_preserves_default_usage_and_alias_wrapping() {
    let help = OverheadCliHelp::help(78);
    assert!(help.starts_with("usage: moru_overhead_report.py [-h] [--days DAYS] [--since SINCE]\n                               [--until UNTIL] [--projects-dir PROJECTS_DIR]\n"));
    assert!(help.contains("  --alias-root ALIAS_ROOT\n                        another checkout path counted as moru-core, such as a\n                        pre-rename path\n"));
    assert!(help.ends_with("  --out OUT\n  --md MD\n"));
    assert!(OverheadCliHelp::help(18).contains("    such as a pre-\n    rename path\n"));
}
