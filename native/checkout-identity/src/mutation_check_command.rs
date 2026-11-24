//! owner: public mutation-check launcher admission.
//! allowed imports: source and encoding guards, arguments and the mutation engine.
//! forbidden imports: workflow admission, specimen mutation and provider calls.
//! callers/tests: launcher and temporary public command fixtures.
//! verification: native path, pre-effect fallback, soft-fail and argument parity.
use crate::{
    mutation_check::MutationCheck, pretool_guard::CallbackGuard, python_encoding::PythonEncoding,
};
#[path = "mutation_check_args.rs"]
mod arguments;
use arguments::Parsed;
use std::{
    env,
    ffi::{CString, OsString},
    os::unix::ffi::OsStrExt,
    path::PathBuf,
};

pub(crate) struct MutationCheckCommand;

impl MutationCheckCommand {
    pub(crate) fn dispatch(launcher: &OsString, args: &[OsString]) {
        let Some((alias, options)) = args.split_first() else {
            return;
        };
        if alias != "mutation-check" {
            return;
        }
        let Some(code) = Self::try_run(launcher, options) else {
            crate::exec_python(launcher, args)
        };
        if code == 130 {
            std::process::exit(code);
        }
        crate::finish(code);
    }

    fn try_run(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        if env::var_os("MORU_LAUNCHER_BACKEND")
            .as_deref()
            .is_some_and(|mode| mode != "auto" && mode != "rust")
            || !PythonEncoding::utf8()
        {
            return None;
        }
        let source = CallbackGuard::root(launcher, "mutation-check")?;
        match Parsed::parse(args, &source)? {
            Parsed::Help => Parsed::show_help(),
            Parsed::Error(message) => Parsed::show_error(message),
            Parsed::Run {
                spec,
                selector,
                root,
            } => {
                let python = Self::python()?;
                MutationCheck::try_run(spec, root, python.to_str()?, selector, Some(&source))
            }
        }
    }

    fn python() -> Option<PathBuf> {
        for directory in env::split_paths(&env::var_os("PATH")?) {
            if !directory.is_absolute() {
                return None;
            }
            let path = directory.join("python3");
            let name = CString::new(path.as_os_str().as_bytes()).ok()?;
            if path.is_file() && unsafe { libc::access(name.as_ptr(), libc::X_OK) } == 0 {
                return Some(path);
            }
        }
        None
    }
}
