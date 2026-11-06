use super::*;
#[test]
fn normalization_redacts_paths_ids_tools_and_counts_unicode_characters() {
    assert_eq!(
        OverheadText::normalize(
            " Tao Agent OS  policy note: /private/Users/me/file, 0123456789abcdef toolu_private "
        ),
        Some("Moru Core policy note: <path>, <id> <toolu>".into())
    );
    assert_eq!(
        OverheadText::normalize(&"한".repeat(121))
            .unwrap()
            .chars()
            .count(),
        120
    );
    assert!(OverheadText::normalize("toolu_한글").is_none());
    assert_eq!(
        OverheadText::text(
            &Py::parse(r#"[{"text":"one","content":"ignored"},{"content":[null,false]},3]"#)
                .unwrap()
        ),
        "one\nNone\nFalse\n3"
    );
}
#[test]
fn launcher_known_unknown_workflow_and_search_boundaries() {
    assert_eq!(
        OverheadText::launcher("'/tmp/moru-hook' workflow query", true),
        Some(Some("workflow query".into()))
    );
    assert_eq!(
        OverheadText::launcher("moru-hook unknown", true),
        Some(Some("other".into()))
    );
    assert_eq!(
        OverheadText::launcher("moru-hook unknown", false),
        Some(Some("unknown".into()))
    );
    assert!(OverheadText::launcher("moru-hook start한", true).is_none());
    assert_eq!(
        OverheadText::search(" \u{85}git\tlog 'moru-hook start'"),
        Some(true)
    );
    assert_eq!(OverheadText::search("rgrep moru-hook start"), Some(false));
    assert_eq!(OverheadText::mark("notMoru"), Some(false));
    assert_eq!(OverheadText::mark("[Moru]"), Some(true));
    assert_eq!(OverheadText::note("POLİCY NOTE"), true);
}
#[test]
fn guidance_recognizes_worktrees_without_expanding_paths() {
    let roots = vec!["/repo/moru-core".into()];
    for path in [
        "/repo/moru-core/common/a.md",
        "/repo/moru-core-worktrees/task/docs/a.md",
        "/repo/moru-core/.moru/worktrees/task/platforms/a.md",
    ] {
        assert!(OverheadText::guidance(&Value::String(path.into()), &roots));
    }
    assert!(!OverheadText::guidance(
        &Value::String(
            "/repo/moru-core/.moru/worktrees/task/.claude/worktrees/task/docs/a.md".into()
        ),
        &roots
    ));
    assert_eq!(
        OverheadText::bash_guidance("cat /repo/moru-core/docs/a.md"),
        Some(true)
    );
    assert_eq!(
        OverheadText::bash_guidance("cat nothing | echo /repo/moru-core/docs/a.md"),
        Some(false)
    );
    assert_eq!(
        OverheadText::bash_guidance("cat /repo/moru-core;x/docs/a.md"),
        Some(true)
    );
    assert_eq!(
        OverheadText::bash_guidance("cat /repo/moru-core/docs/.md"),
        Some(false)
    );
}
