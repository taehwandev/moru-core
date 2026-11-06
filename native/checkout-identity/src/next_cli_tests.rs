use super::*;
fn parse(words: &[&str]) -> Option<NextCli> {
    NextCli::parse(
        &words.iter().map(OsString::from).collect::<Vec<_>>(),
        Path::new("/default"),
    )
}
#[test]
fn ordering_repeated_abbreviated_and_inline_values() {
    let cli = parse(&[
        "--f=json",
        "--e",
        "old",
        "--pro",
        "/first",
        "--evidence=new",
        "--project=/last",
    ])
    .unwrap();
    assert!(cli.exit.is_none());
    assert_eq!(cli.project, Path::new("/last"));
    assert_eq!(cli.evidence.unwrap(), Path::new("new"));
    assert_eq!(cli.format, "json");
}
#[test]
fn help_preempts_unknown_but_not_invalid_choice() {
    assert_eq!(parse(&["unknown", "--help"]).unwrap().exit.unwrap().0, 0);
    let exit = parse(&["--format=bad", "--help"]).unwrap().exit.unwrap();
    assert_eq!(exit.0, 2);
    assert!(exit
        .1
        .contains("invalid choice: 'bad' (choose from 'markdown', 'json')"));
    assert!(exit.2);
    assert!(parse(&["--", "--help"])
        .unwrap()
        .exit
        .unwrap()
        .1
        .contains("unrecognized arguments: -- --help"));
}
#[test]
fn ambiguity_and_negative_classification_match_builder() {
    assert!(NextCli::option("--format=bad value"));
    assert!(!NextCli::option("--unknown value"));
    assert!(NextCli::name("--=x")
        .unwrap_err()
        .contains("--help, --project, --evidence, --format"));
    assert!(!NextCli::option("-1\n"));
    assert_eq!(
        NextCli::option("-1tail"),
        env!("MORU_ARGPARSE_NEGATIVE_NUMBER") != "prefix"
    );
    assert_eq!(
        NextCli::option("-1\n\n"),
        env!("MORU_ARGPARSE_NEGATIVE_NUMBER") != "prefix"
    );
}
#[test]
fn width_40_usage_is_exact() {
    assert_eq!(render::CliRender::usage(38), "usage: agent_next_action.py [-h]\n                            [--project PROJECT]\n                            [--evidence EVIDENCE]\n                            [--format {markdown,json}]\n");
    let help = render::CliRender::help(38);
    assert!(help.contains("  -h, --help      show this help\n                  message and exit\n"));
    assert!(help.contains("  --evidence EVIDENCE\n                  Explicit\n                  preflight.json path.\n"));
}
