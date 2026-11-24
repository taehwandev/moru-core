//! owner: lesson compaction alias and ordered per-lesson dispatch.
//! allowed imports: source guard, shared reports and locked compaction operations.
//! forbidden imports: direct writes, lock management and workflow authority.
//! callers/tests: native launcher and lesson compaction process fixtures.
//! verification: exact dry-run output with original argv fallback before output.
use super::{
    lesson_compaction_apply::LessonCompactionApply,
    lesson_compaction_preview::LessonCompactionPreview,
};
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding, statusline::Renderer};
use serde_json::{json, Value};
use std::{
    env,
    ffi::OsString,
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};

pub(crate) struct LessonCompactionCli;

struct Run {
    report: Value,
    policy: Value,
    cutoff: i64,
    micros: i64,
}

impl LessonCompactionCli {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let (apply, state_args) = match &args[1..] {
            [flag, rest @ ..] if flag == "--apply" => (true, rest),
            [rest @ .., flag] if flag == "--apply" => (true, rest),
            rest => (false, rest),
        };
        let Some(state) = Self::state_home(state_args) else {
            crate::exec_python(launcher, args)
        };
        let Some(root) =
            CallbackGuard::root(launcher, "lessons-compact").filter(|_| PythonEncoding::utf8())
        else {
            crate::exec_python(launcher, args);
        };
        let Some(run) = Self::prepare(&state, apply) else {
            crate::exec_python(launcher, args)
        };
        let result =
            Self::write(run.report["output"].as_str().unwrap_or_default()).and_then(|()| {
                if apply && run.report.get("folds").is_some() {
                    Self::apply(&root, run)
                } else {
                    Ok(0)
                }
            });
        match result {
            Ok(code) => code,
            Err(error) => {
                eprintln!("lessons-compact: {error}");
                1
            }
        }
    }

    fn write(text: &str) -> io::Result<()> {
        let mut stdout = io::stdout().lock();
        stdout.write_all(text.as_bytes())?;
        stdout.flush()
    }

    fn apply(root: &Path, mut run: Run) -> io::Result<i32> {
        let folds = run.report["folds"]
            .as_array()
            .ok_or_else(|| io::Error::other("missing folds"))?;
        let stale = run.report["stale"]
            .as_array()
            .ok_or_else(|| io::Error::other("missing stale lessons"))?;
        let removed = &run.report["removed"];
        let mut written = 0;
        for (index, fold) in folds.iter().enumerate() {
            run.policy["lesson_id"] = fold[0].clone();
            run.policy["known"] = fold[1].clone();
            match LessonCompactionApply::fold(&run.policy, true) {
                Some(result) => written += usize::from(result?),
                None => {
                    return Self::resume(
                        root,
                        json!({
                            "inbox": run.policy["inbox"], "folds": &folds[index..], "stale": stale,
                            "micros": run.micros, "removed": removed, "written": written, "marked": 0,
                        }),
                    )
                }
            }
        }
        Self::write(&format!(
            "folded {written} lessons; {removed} files removed\n"
        ))?;
        let mut marked = 0;
        for (index, lesson) in stale.iter().enumerate() {
            run.policy["lesson_id"] = lesson.clone();
            match LessonCompactionApply::mark_at(&run.policy, run.cutoff, true) {
                Some(result) => marked += usize::from(result?),
                None => {
                    return Self::resume(
                        root,
                        json!({
                            "inbox": run.policy["inbox"], "folds": null, "stale": &stale[index..],
                            "micros": run.micros, "removed": removed, "written": written, "marked": marked,
                        }),
                    )
                }
            }
        }
        Self::write(&format!("marked {marked} lessons stale\n"))?;
        Ok(0)
    }

    fn resume(root: &Path, payload: Value) -> io::Result<i32> {
        let bytes = serde_json::to_vec(&payload)?;
        let mut child = Command::new("python3")
            .args([
                "-c",
                "import runpy, sys; runpy.run_path(sys.argv[1])['_resume_compaction']()",
            ])
            .arg(root.join("scripts/lessons-compact.py"))
            .env("MORU_LAUNCHER_BACKEND", "python")
            .stdin(Stdio::piped())
            .spawn()?;
        let result = child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("missing continuation input"))
            .and_then(|mut input| input.write_all(&bytes));
        let status = child.wait()?;
        result?;
        Ok(status.code().unwrap_or(1))
    }

    fn state_home(args: &[OsString]) -> Option<PathBuf> {
        let state = match args {
            [] => {
                let state = env::var("MORU_STATE_HOME").unwrap_or_default();
                let state = Renderer::strip(&state);
                if state.is_empty() {
                    PathBuf::from(env::var("HOME").ok()?).join(".moru")
                } else {
                    PathBuf::from(state)
                }
            }
            [flag, state] if flag == "--state-home" => PathBuf::from(state),
            [flag] => PathBuf::from(flag.to_str()?.strip_prefix("--state-home=")?),
            _ => return None,
        };
        let normalized: PathBuf = state.components().collect();
        (state.is_absolute() && state.as_os_str() == normalized.as_os_str()).then_some(state)
    }

    fn prepare(state: &Path, apply: bool) -> Option<Run> {
        const DAY: i64 = 86_400_000_000;
        const EPOCH: i64 = 719163 * DAY;
        const STORE: &str = include_str!("../../../scripts/agent_lesson_store.py");
        const LESSONS: &str = include_str!("../../../scripts/agent_block_lessons.py");
        let inbox = state.join("lessons/inbox");
        let path = inbox.to_str()?;
        let present = match fs::metadata(&inbox) {
            Ok(meta) => meta.is_dir(),
            Err(error) if error.kind() == io::ErrorKind::NotFound => false,
            Err(_) => return None,
        };
        if !present {
            return Some(Run {
                report: json!({"output": format!("no candidate inbox at {path}\n")}),
                policy: Value::Null,
                cutoff: 0,
                micros: 0,
            });
        }
        let limit: usize = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")?
            .parse()
            .ok()?;
        let keys = Self::constant(STORE, "OCCURRENCE_KEY_HISTORY_LIMIT = ", "")?
            .try_into()
            .ok()?;
        let days = Self::constant(STORE, "RECENT_OCCURRENCE_DAYS = ", "")?.checked_sub(1)?;
        let stale =
            Self::constant(LESSONS, "STALE_AFTER = timedelta(days=", ")")?.checked_mul(DAY)?;
        let micros = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_micros()
            .try_into()
            .ok()?;
        let cutoff = EPOCH.checked_add(micros)?.checked_sub(stale)?;
        if keys == 0 || days < 0 || stale < 0 {
            return None;
        }
        let report = LessonCompactionPreview::report_at(path, limit, keys, days, cutoff, apply)?;
        if apply && serde_json::to_vec(&report).ok()?.len() > 512 * 1024 {
            return None;
        }
        let policy = json!({"inbox": path, "key_limit": keys, "recent_days": days + 1, "digit_limit": limit});
        Some(Run {
            report,
            policy,
            cutoff,
            micros,
        })
    }

    fn constant(source: &str, prefix: &str, suffix: &str) -> Option<i64> {
        source
            .lines()
            .find_map(|line| line.strip_prefix(prefix))?
            .strip_suffix(suffix)?
            .parse()
            .ok()
    }
}
