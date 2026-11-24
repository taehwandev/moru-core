//! owner: source-bound mutation-check execution after CLI argument parsing.
//! allowed imports: bounded file I/O, JSON, interrupt handling and fixed unittest invocation.
//! forbidden imports: workflow authority, provider calls and output-based verdicts.
//! callers/tests: direct mutation-check CLI and temporary restoration fixtures.
//! verification: exactly one text match, status-based verdicts and no post-write replay.
use crate::cards_resume_signal::ResumeInterrupt;
use serde_json::Value;
use std::{
    ffi::{OsStr, OsString},
    fs::{self, File, OpenOptions},
    io::{self, Read, Seek, Write},
    os::unix::{
        fs::{MetadataExt, OpenOptionsExt},
        process::CommandExt,
    },
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
};

const LIMIT: u64 = 1024 * 1024;

pub(crate) struct MutationCheck;

struct Mutant<'a> {
    target: PathBuf,
    label: &'a str,
    old: &'a str,
    new: &'a str,
}

impl MutationCheck {
    pub(crate) fn run(script: &OsStr, args: &[OsString]) -> i32 {
        let [python, spec, root, selector, original @ ..] = args else {
            return 2;
        };
        let root = Path::new(root);
        let plan = Self::read_limited(Self::open(Path::new(spec), false))
            .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok());
        if let (Some(plan), Ok(root), Some(python_text), Some(selector_text)) = (
            plan,
            root.canonicalize(),
            python.to_str(),
            selector.to_str(),
        ) {
            if let Some(mutants) = Self::prepare(&plan, &root) {
                return match ResumeInterrupt::install()
                    .and_then(|_interrupt| Self::check(&mutants, &root, python_text, selector_text))
                {
                    Ok(code) => code,
                    Err(error) => {
                        eprintln!("mutation check failed: {error}");
                        1
                    }
                };
            }
        }
        // Only this preflight branch may replay the original CLI.
        let error = Command::new(python)
            .arg(script)
            .args(original)
            .env("MORU_MUTATION_REFERENCE_REPLAY", "1")
            .exec();
        eprintln!("mutation check fallback failed: {error}");
        1
    }

    fn prepare<'a>(plan: &'a Value, root: &Path) -> Option<Vec<Mutant<'a>>> {
        plan.as_array()?
            .iter()
            .map(|row| {
                let field = |name| row.get(name)?.as_str().filter(|value| !value.is_empty());
                let relative = Path::new(field("file")?);
                if !relative
                    .components()
                    .all(|part| matches!(part, Component::Normal(_)))
                {
                    return None;
                }
                let target = root.join(relative);
                if target.canonicalize().ok()? != target {
                    return None;
                }
                let source = Self::read_limited(Self::open(&target, false))?;
                if source.contains(&b'\r') || std::str::from_utf8(&source).is_err() {
                    return None;
                }
                Some(Mutant {
                    target,
                    label: field("label")?,
                    old: field("old")?,
                    new: field("new")?,
                })
            })
            .collect()
    }

    fn open(path: &Path, writable: bool) -> io::Result<File> {
        let file = OpenOptions::new()
            .read(true)
            .write(writable)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)?;
        let metadata = file.metadata()?;
        if !metadata.is_file() || metadata.nlink() != 1 {
            return Err(io::Error::other(
                "expected a regular mutation target with one link",
            ));
        }
        Ok(file)
    }

    fn read_limited(file: io::Result<File>) -> Option<Vec<u8>> {
        let mut bytes = Vec::new();
        file.ok()?.take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        (bytes.len() as u64 <= LIMIT).then_some(bytes)
    }

    fn check(mutants: &[Mutant<'_>], root: &Path, python: &str, selector: &str) -> io::Result<i32> {
        let mut stdout = io::stdout().lock();
        writeln!(stdout, "check: {python} -m unittest {selector}")?;
        let (mut killed, mut unapplied) = (0, 0);
        for mutant in mutants {
            if ResumeInterrupt::interrupted() {
                return Ok(130);
            }
            let verdict = match Self::judge(mutant, root, python, selector)? {
                Some(true) => {
                    killed += 1;
                    "KILLED"
                }
                Some(false) => "SURVIVED",
                None => {
                    unapplied += 1;
                    "NOT APPLIED"
                }
            };
            if ResumeInterrupt::interrupted() {
                return Ok(130);
            }
            writeln!(stdout, "{verdict:>11}  {}", mutant.label)?;
        }
        writeln!(stdout, "{killed}/{} killed", mutants.len())?;
        if unapplied != 0 {
            writeln!(
                stdout,
                "{unapplied} mutant(s) never applied: the `old` text was not found exactly once"
            )?;
        }
        stdout.flush()?;
        Ok(i32::from(killed != mutants.len()))
    }

    fn judge(
        mutant: &Mutant<'_>,
        root: &Path,
        python: &str,
        selector: &str,
    ) -> io::Result<Option<bool>> {
        if mutant.target.canonicalize()? != mutant.target {
            return Err(io::Error::other("mutation target changed after preflight"));
        }
        let mut file = Self::open(&mutant.target, false)?;
        let mut original = String::new();
        (&mut file).take(LIMIT + 1).read_to_string(&mut original)?;
        if original.len() as u64 > LIMIT || original.contains('\r') {
            return Err(io::Error::other(
                "mutation target text profile changed after preflight",
            ));
        }
        if original.matches(mutant.old).count() != 1 {
            return Ok(None);
        }
        let identity = file.metadata()?;
        let mut writable = Self::open(&mutant.target, true)?;
        let target = writable.metadata()?;
        if (target.dev(), target.ino()) != (identity.dev(), identity.ino()) {
            return Err(io::Error::other(
                "mutation target identity changed after preflight",
            ));
        }
        let mutated = original.replacen(mutant.old, mutant.new, 1);
        let result = Self::replace(&mut writable, &mutated).and_then(|()| {
            if ResumeInterrupt::interrupted() {
                return Ok(false);
            }
            Command::new(python)
                .args(["-m", "unittest", selector])
                .current_dir(root)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .map(|status| !status.success())
        });
        Self::restore(&mut writable, &mutant.target, &original)?;
        result.map(Some)
    }

    fn restore(opened: &mut File, path: &Path, original: &str) -> io::Result<()> {
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("target has no parent"))?;
        if parent.canonicalize()? != parent {
            return Err(io::Error::other(
                "mutation target directory changed during the check",
            ));
        }
        match fs::symlink_metadata(path) {
            Ok(current) => {
                let before = opened.metadata()?;
                if (current.dev(), current.ino()) == (before.dev(), before.ino()) {
                    Self::replace(opened, original)
                } else {
                    Self::replace(&mut Self::open(path, true)?, original)
                }
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                let mut restored = OpenOptions::new().write(true).create_new(true).open(path)?;
                Self::replace(&mut restored, original)
            }
            Err(error) => Err(error),
        }
    }

    fn replace(file: &mut File, text: &str) -> io::Result<()> {
        file.rewind()?;
        file.write_all(text.as_bytes())?;
        file.set_len(text.len() as u64)
    }
}
