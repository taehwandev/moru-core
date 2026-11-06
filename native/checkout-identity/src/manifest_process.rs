//! Owner: source-bound external skill manifest CLI ingress.
//! Allowed: existing guard/checker owners, std I/O. Forbidden: source downloads,
//! installation, credentials, policy changes or implicit remote checks.
//! Callers/tests: launcher_main; native manifest process parity and bundle smoke.
use std::{ffi::OsString, io::Write};

pub(crate) struct ManifestProcess;

impl ManifestProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        let Some(root) = crate::pretool_guard::CallbackGuard::root(launcher, "git") else {
            crate::exec_python(launcher, args);
        };
        if args[0] == "check-react-rn-skill-manifest" {
            return crate::react_manifest::ReactManifest::run(&root, &args[1..])
                .unwrap_or_else(|| crate::exec_python(launcher, args));
        }
        // The original Android entry ignores argv entirely.
        let (code, output, error) = match crate::android_manifest::AndroidManifest::evaluate(&root) {
            Ok(result) => result,
            Err(_) => crate::exec_python(launcher, args),
        };
        if std::io::stdout().write_all(output.as_bytes()).is_err()
            || std::io::stderr().write_all(error.as_bytes()).is_err()
        {
            return 1;
        }
        code
    }
}
