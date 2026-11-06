use super::*;
#[test]
fn parse_precedence_and_values() {
    let parse = |args: &[&str]| {
        ReactManifestCli::parse(
            Path::new("."),
            &args.iter().map(OsString::from).collect::<Vec<_>>(),
        )
        .unwrap()
    };
    assert_eq!(parse(&["--unknown", "--help"]).exit, Some(0));
    assert_eq!(parse(&["--=x"]).exit, Some(2));
    assert_eq!(parse(&["--help", "--=x"]).exit, Some(2));
    assert_eq!(parse(&["--manifest", "--help"]).exit, Some(2));
    assert_eq!(parse(&["--manifest", "-1\n", "--help"]).exit, Some(0));
    assert_eq!(parse(&["--manifest", "-1\n\n", "--help"]).exit, Some(2));
    assert_eq!(parse(&["--", "--help"]).exit, Some(2));
    assert_eq!(parse(&["-hh"]).exit, Some(0));
    assert_eq!(parse(&["-hfoo"]).exit, Some(2));
    let valid = parse(&["--m=one", "--manifest", "-1", "--s=", "--r"]);
    assert_eq!(valid.manifest, PathBuf::from("-1"));
    assert_eq!(valid.source, Some(PathBuf::from("")));
    assert!(valid.remote);
    assert_eq!(valid.exit, None);
}
#[test]
fn value_classification() {
    for value in ["-1", "-.2", "-1.2", "-1\n", "-.2\n", "-", "-a b", ""] {
        assert_eq!(ReactManifestCli::option(value), Some(false));
    }
    for value in ["-1e2", "-1.", "-1\n\n", "--help", "--"] {
        assert_eq!(ReactManifestCli::option(value), Some(true));
    }
}
#[test]
fn default_help_layout() {
    assert_eq!(ReactManifestCli::help(78).unwrap().replace(option_env!("MORU_ARGPARSE_OPTIONS_TITLE").unwrap_or("optional arguments:"), "optional arguments:"),"usage: check_react_rn_external_skill_manifest.py [-h] [--manifest MANIFEST]\n                                                 [--source-root SOURCE_ROOT]\n                                                 [--remote-check]\n\nValidate the reviewed React/RN external skill source manifest.\n\noptional arguments:\n  -h, --help            show this help message and exit\n  --manifest MANIFEST\n  --source-root SOURCE_ROOT\n  --remote-check        compare each pinned commit with the provider's current\n                        remote HEAD; requires network access and is never run\n                        by the default offline check\n");
}
#[test]
fn narrow_usage_layout() {
    assert_eq!(ReactManifestCli::usage(38),"usage: check_react_rn_external_skill_manifest.py\n       [-h] [--manifest MANIFEST]\n       [--source-root SOURCE_ROOT]\n       [--remote-check]\n");
}
