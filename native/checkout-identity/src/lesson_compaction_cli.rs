//! owner: native read-only lesson compaction alias admission.
//! allowed imports: source guard, Python encoding and existing dry-run report.
//! forbidden imports: writes, locks and mutation authority.
//! callers/tests: native launcher and lesson compaction process fixtures.
//! verification: exact dry-run output with original argv fallback before output.
use super::lesson_compaction_preview::LessonCompactionPreview;
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding, statusline::Renderer};
use std::{
    env,
    ffi::OsString,
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub(crate) struct LessonCompactionCli;

impl LessonCompactionCli {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(state) = Self::state_home(&args[1..]) else {
            crate::exec_python(launcher, args)
        };
        if !PythonEncoding::utf8() || CallbackGuard::root(launcher, "lessons-compact").is_none() {
            crate::exec_python(launcher, args);
        }
        let Some(output) = Self::output(&state) else {
            crate::exec_python(launcher, args)
        };
        let mut stdout = io::stdout().lock();
        if stdout
            .write_all(output.as_bytes())
            .and_then(|()| stdout.flush())
            .is_ok()
        {
            0
        } else {
            1
        }
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

    fn output(state: &Path) -> Option<String> {
        const DAY: i64 = 86_400_000_000;
        const EPOCH: i64 = 719163 * DAY;
        const STORE: &str = include_str!("../../../scripts/agent_lesson_store.py");
        const LESSONS: &str = include_str!("../../../scripts/agent_block_lessons.py");
        let inbox = state.join("lessons/inbox");
        let path = inbox.to_str()?;
        match fs::metadata(&inbox) {
            Ok(meta) if meta.is_dir() => {}
            Ok(_) => return Some(format!("no candidate inbox at {path}\n")),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Some(format!("no candidate inbox at {path}\n"));
            }
            Err(_) => return None,
        }
        let limit = option_env!("MORU_PYTHON_INT_MAX_STR_DIGITS")?
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
        let report = LessonCompactionPreview::dry_run(path, limit, keys, days, cutoff)?;
        Some(report.get("output")?.as_str()?.to_owned())
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
