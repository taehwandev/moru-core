//! owner: CardResumeProcess; allowed imports: guarded card readers/domain/input,
//! std/libc and fixed Codex command; forbidden imports: SQL/state/session writes,
//! authority inference, auto-selection or fallback after UI/input/dispatch;
//! callers/tests: CardsProcess; real CLI/PTY and fake-provider conformance tests.
use crate::{
    cards_identity::CardRepository, cards_process::CardsProcess, cards_resume::CardResume,
    cards_resume_child::CardResumeChild, cards_resume_input::CardResumeInput,
    cards_resume_output::CardResumeOutput, cards_resume_signal::ResumeInterrupt,
    cards_store::CardStore,
};
use serde_json::json;
use std::{
    env,
    ffi::{CString, OsString},
    fs,
    io::{self, Write},
    os::unix::ffi::OsStrExt,
    path::{Path, PathBuf},
};

pub(crate) struct CardResumeProcess;

impl CardResumeProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        let project = match args {
            [word] if word == "resume" => env::current_dir().ok()?,
            [flag, path, word] if flag == "--project" && word == "resume" => PathBuf::from(path),
            _ => return None,
        };
        if !CardResumeInput::supported()
            || unsafe { libc::getuid() != libc::geteuid() || libc::getgid() != libc::getegid() }
        {
            return None;
        }
        let (project, state) = CardsProcess::resolve(launcher, project)?;
        project.to_str()?;
        if !project.is_dir() {
            return None;
        }
        let repo = CardRepository::key(&project)?;
        let snapshot = match CardStore::open(&state.join("work-cards/cards.sqlite3"))? {
            Some(store) => store.snapshot(&repo, true)?,
            None => json!([]),
        };
        let choices = CardResume::menu(&snapshot)?;
        if choices.is_empty() {
            return Some(Self::error(
                "no tasks with a recorded Codex session in this repository",
            ));
        }
        let mut output = CardResumeOutput::new().ok()?;
        // Everything that could decline has completed; subsequent failures and
        // effects are final, with no Python replay after exposing the menu.
        let status = Self::pick(&project, &choices, &mut output);
        Some(output.finish(status))
    }

    fn pick(project: &Path, choices: &[(String, String)], output: &mut CardResumeOutput) -> i32 {
        let printed = output
            .print("Codex tasks (choose a number; Enter cancels):")
            .and_then(|_| choices.iter().try_for_each(|(line, _)| output.print(line)));
        if let Err(error) = printed {
            return Self::error(&CardResumeOutput::os_error(&error, None));
        }
        let index = match CardResumeInput::choose(choices.len(), output) {
            Ok(Some(index)) => index,
            Ok(None) => return 0,
            Err(message) => return Self::error(&message),
        };
        if ResumeInterrupt::interrupted() {
            Self::operator_interrupt(output);
        }
        Self::launch(project, &choices[index].1, output)
    }

    fn launch(project: &Path, session: &str, output: &mut CardResumeOutput) -> i32 {
        // Preserve cwd diagnostics before trying the provider. Neither permission
        // nor session authority is widened; Codex owns its native permission flow.
        if let Err(error) = Self::directory(project) {
            return Self::error(&CardResumeOutput::os_error(&error, project.to_str()));
        }
        match CardResumeChild::run(project, session) {
            Ok(Some(status)) => status,
            Ok(None) => Self::operator_interrupt(output),
            Err(error) => {
                let filename = if Self::directory(project).is_err() {
                    project.to_str()
                } else {
                    Some("codex")
                };
                Self::error(&CardResumeOutput::os_error(&error, filename))
            }
        }
    }

    fn directory(project: &Path) -> io::Result<()> {
        if !fs::metadata(project)?.is_dir() {
            return Err(io::Error::from_raw_os_error(libc::ENOTDIR));
        }
        let path = CString::new(project.as_os_str().as_bytes())
            .map_err(|_| io::Error::from_raw_os_error(libc::EINVAL))?;
        if unsafe { libc::access(path.as_ptr(), libc::X_OK) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    fn error(message: &str) -> i32 {
        let _ = writeln!(io::stderr(), "work cards: {message}");
        2
    }

    fn operator_interrupt(output: &mut CardResumeOutput) -> ! {
        let _ = writeln!(io::stderr(), "KeyboardInterrupt");
        output.flush_warning();
        unsafe {
            libc::signal(libc::SIGINT, libc::SIG_DFL);
            libc::raise(libc::SIGINT);
        }
        std::process::exit(130);
    }
}
