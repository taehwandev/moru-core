//! Owner: Android snapshot/manifest comparison and bounded Git identity reads.
//! Allowed: std filesystem/process/thread primitives. Forbidden: network,
//! snapshot installation, writes, Python execution or lifecycle authority.
//! Callers/tests: native manifest ingress; unit vectors and process parity tests.
use std::{collections::BTreeSet, fs, io::{self, Read}, path::Path,
    process::{Command, Stdio}, sync::mpsc, thread, time::{Duration, Instant}};

const MANIFEST: &str = "platforms/android/skills/android-external-skill-source-coverage/references/current-guidance.md";
const SOURCES: &[(&str, &str)] = &[
    ("android", "/private/tmp/notmid-moru-source-android-skills"),
    ("compose", "/private/tmp/notmid-moru-source-compose-performance-skills"),
    ("chrisbanes", "/private/tmp/notmid-moru-source-chrisbanes-skills"),
];

pub(crate) struct AndroidManifest;

impl AndroidManifest {
    pub(crate) fn evaluate(root: &Path) -> io::Result<(i32, String, String)> {
        let sources: Vec<_> = SOURCES.iter().map(|(name, path)| (*name, Path::new(path))).collect();
        Self::evaluate_with_sources(root, &sources)
    }

    fn evaluate_with_sources(root: &Path, sources: &[(&str, &Path)]) -> io::Result<(i32, String, String)> {
        let manifest = root.join(MANIFEST);
        if !manifest.try_exists()? {
            return Ok((1, String::new(), format!("missing manifest: {}\n", manifest.display())));
        }
        let text = fs::read_to_string(manifest)?.replace("\r\n", "\n").replace('\r', "\n");
        let mut out = String::new();
        let mut err = String::new();
        let mut failed = false;
        for (name, source) in sources {
            if !source.try_exists()? {
                err.push_str(&format!("[{name}] missing source snapshot: {}\n", source.display()));
                failed = true;
                continue;
            }
            let mut actual = BTreeSet::new();
            walk(source, source, &mut actual)?;
            let listed = listed(&text, source);
            let missing: Vec<_> = actual.difference(&listed).collect();
            let stale: Vec<_> = listed.difference(&actual).collect();
            let head = head(source)?;
            out.push_str(&format!("[{name}] commit={head} actual={} listed={} missing={} stale={}\n",
                actual.len(), listed.len(), missing.len(), stale.len()));
            for (label, paths) in [("missing", missing), ("stale", stale)] {
                if !paths.is_empty() {
                    failed = true;
                    out.push_str(&format!("{label}:\n"));
                    for path in paths { out.push_str(&format!("- {path}\n")); }
                }
            }
        }
        Ok((i32::from(failed), out, err))
    }
}

fn walk(root: &Path, directory: &Path, files: &mut BTreeSet<String>) -> io::Result<()> {
    let entries = match fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) if matches!(error.kind(), io::ErrorKind::PermissionDenied | io::ErrorKind::NotADirectory) => return Ok(()),
        Err(error) => return Err(error),
    };
    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        if path.is_file() {
            let relative = path.strip_prefix(root).map_err(io::Error::other)?;
            let relative = relative.to_str().ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "non-UTF-8 snapshot path"))?;
            if relevant(relative) { files.insert(relative.to_owned()); }
        }
        // pathlib rglob does not descend through directory symlinks.
        if entry.file_type()?.is_dir() { walk(root, &path, files)?; }
    }
    Ok(())
}

fn relevant(path: &str) -> bool {
    matches!(path.rsplit('/').next().unwrap_or(""), "SKILL.md" | "README.md" | "INDEX.md" |
        "CONTRIBUTING.md" | "AGENTS.md" | "CLAUDE.md" | "skills.schema.json")
        || path.contains("/references/") || path.starts_with("docs/")
}

fn listed(text: &str, root: &Path) -> BTreeSet<String> {
    let mut result = BTreeSet::new();
    let mut tail = text;
    while let Some(start) = tail.find('`') {
        tail = &tail[start + 1..];
        let Some(end) = tail.find('`') else { break };
        if end == 0 { continue; } // The second tick can start the next match.
        let candidate = &tail[..end];
        if !candidate.starts_with('/') && (candidate.ends_with(".md") || candidate.ends_with(".json"))
            && root.join(candidate).is_file() {
            result.insert(candidate.to_owned());
        }
        tail = &tail[end + 1..];
    }
    result
}

fn head(root: &Path) -> io::Result<String> {
    let mut child = Command::new("git").arg("-C").arg(root).args(["rev-parse", "HEAD"])
        .stdout(Stdio::piped()).stderr(Stdio::null()).spawn()?;
    let mut pipe = child.stdout.take().ok_or_else(|| io::Error::other("missing Git stdout"))?;
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = pipe.read_to_end(&mut bytes).map(|_| bytes);
        let _ = sender.send(result);
    });
    let deadline = Instant::now() + Duration::from_secs(10);
    let status = loop {
        match child.try_wait()? {
            Some(status) => break status,
            None if Instant::now() < deadline => thread::sleep(Duration::from_millis(2)),
            None => { let _ = child.kill(); let _ = child.wait(); return Ok("unknown".into()); }
        }
    };
    let Ok(bytes) = receiver.recv_timeout(deadline.saturating_duration_since(Instant::now())) else {
        return Ok("unknown".into());
    };
    // subprocess text decoding happens even for a failed Git process.
    let text = String::from_utf8(bytes?).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    Ok(if status.success() {
        text.replace("\r\n", "\n").replace('\r', "\n")
            .trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)).to_owned()
    } else { "unknown".into() })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{path::PathBuf, sync::atomic::{AtomicUsize, Ordering}};
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let path = std::env::temp_dir().join(format!("moru-android-manifest-{}-{}",
                std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn write(&self, path: &str, text: &str) {
            let path = self.0.join(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); }
    }
    #[test]
    fn backticks_preserve_noncanonical_names_and_match_nonempty_spans() {
        let fixture = Fixture::new();
        fixture.write("README.md", "");
        fixture.write("line\nbreak.md", "");
        fixture.write("directory/child.json", "");
        let text = "``README.md` `./README.md` `directory//child.json` `line\nbreak.md` `absent.md` `/README.md`";
        let actual = listed(text, &fixture.0);
        assert_eq!(actual, ["README.md", "./README.md", "directory//child.json", "line\nbreak.md"]
            .into_iter().map(str::to_owned).collect());
    }
    #[test]
    fn source_order_sorted_differences_and_unknown_git_are_preserved() {
        let fixture = Fixture::new();
        fixture.write(MANIFEST, "`README.md` `notes.md` `./README.md`\r\n");
        for path in ["snapshot/README.md", "snapshot/notes.md", "snapshot/docs/z.png", "snapshot/docs/a.md"] {
            fixture.write(path, "");
        }
        let source = fixture.0.join("snapshot");
        let absent = fixture.0.join("absent");
        let (code, out, err) = AndroidManifest::evaluate_with_sources(&fixture.0,
            &[("missing-first", &absent), ("second", &source)]).unwrap();
        assert_eq!(code, 1);
        assert_eq!(out, "[second] commit=unknown actual=3 listed=3 missing=2 stale=2\nmissing:\n- docs/a.md\n- docs/z.png\nstale:\n- ./README.md\n- notes.md\n");
        assert_eq!(err, format!("[missing-first] missing source snapshot: {}\n", absent.display()));
        fixture.write(MANIFEST, "`README.md` `docs/a.md` `docs/z.png`");
        // Binary docs are relevant but cannot be listed by the .md/.json filter.
        assert_eq!(AndroidManifest::evaluate_with_sources(&fixture.0, &[("second", &source)]).unwrap().0, 1);
        fs::remove_file(source.join("docs/z.png")).unwrap();
        assert_eq!(AndroidManifest::evaluate_with_sources(&fixture.0, &[("second", &source)]).unwrap().0, 0);
    }
    #[cfg(unix)]
    #[test]
    fn file_symlinks_are_included_but_directory_symlinks_are_not_walked() {
        use std::os::unix::fs::symlink;
        let fixture = Fixture::new();
        fixture.write("source/README.md", "");
        fixture.write("outside/INDEX.md", "");
        let source = fixture.0.join("source");
        symlink("../outside", source.join("docs")).unwrap();
        symlink("../outside/INDEX.md", source.join("SKILL.md")).unwrap();
        symlink("absent", source.join("CLAUDE.md")).unwrap();
        let mut actual = BTreeSet::new();
        walk(&source, &source, &mut actual).unwrap();
        assert_eq!(actual, ["README.md", "SKILL.md"].into_iter().map(str::to_owned).collect());
        assert!(listed("`docs/INDEX.md`", &source).contains("docs/INDEX.md"));
    }
    #[test]
    fn coverage_preserves_root_reference_exclusion_and_nested_rules() {
        for path in ["SKILL.md", "x/README.md", "x/references/code.kt", "docs/image.png", "x/skills.schema.json"] {
            assert!(relevant(path), "{path}");
        }
        for path in ["references/code.kt", "readme.md", "x/docs/code.kt", "code.kt"] {
            assert!(!relevant(path), "{path}");
        }
    }
    #[test]
    fn missing_manifest_keeps_diagnostic_and_exit() {
        let root = Path::new("/nonexistent-moru-manifest-unit-fixture");
        let (code, out, err) = AndroidManifest::evaluate(root).unwrap();
        assert_eq!(code, 1);
        assert!(out.is_empty());
        assert_eq!(err, format!("missing manifest: {}\n", root.join(MANIFEST).display()));
    }
}
