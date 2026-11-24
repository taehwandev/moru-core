//! owner: disposable Git fixture for the smoke CLI.
//! allowed imports: tempfile allocation, local fixture files and fixed Git commands.
//! forbidden imports: real checkout mutation, network clients and workflow policy.
//! callers/tests: SmokeHookSuite and test_run_smoke_checks process tests.
//! verification: scratch-only Git setup and cleanup on success and failure.
use std::{
    ffi::OsStr,
    fs, io,
    os::unix::ffi::OsStrExt,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

pub(crate) struct SmokeWorkspace(PathBuf);

impl SmokeWorkspace {
    pub(crate) fn allocate(parent: &Path) -> io::Result<Self> {
        let template = parent.join("tmpXXXXXX");
        let mut bytes = template.as_os_str().as_bytes().to_vec();
        bytes.push(0);
        // mkdtemp atomically creates a new, owner-only directory and edits the
        // caller-owned NUL-terminated buffer in place.
        if unsafe { libc::mkdtemp(bytes.as_mut_ptr().cast()) }.is_null() {
            return Err(io::Error::last_os_error());
        }
        bytes.pop();
        Ok(Self(PathBuf::from(OsStr::from_bytes(&bytes))))
    }

    pub(crate) fn path(&self) -> &Path {
        &self.0
    }

    pub(crate) fn prepare(&self, root: &Path) -> io::Result<()> {
        self.git(&["init"])?;
        self.git(&["config", "user.name", "Test User"])?;
        self.git(&["config", "user.email", "test@example.com"])?;
        fs::write(self.0.join("README.md"), "Dummy project")?;
        self.git(&["add", "README.md"])?;
        self.git(&["commit", "-m", "Initial commit"])?;
        fs::copy(root.join(".vibeguard.json"), self.0.join(".vibeguard.json"))?;
        Ok(())
    }

    fn git(&self, args: &[&str]) -> io::Result<()> {
        println!("Running command: git {}", args.join(" "));
        let status = Command::new("git")
            .args(args)
            .current_dir(&self.0)
            .env("GIT_DIR", self.0.join(".git"))
            .env("GIT_WORK_TREE", &self.0)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()?;
        if status.success() {
            Ok(())
        } else {
            Err(io::Error::other(format!(
                "git {} exited with {status}",
                args[0]
            )))
        }
    }
}

impl Drop for SmokeWorkspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
