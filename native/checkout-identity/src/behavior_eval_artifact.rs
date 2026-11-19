//! owner: offline grader artifact reads; allowed imports: std filesystem and libc.
//! forbidden imports: writes, providers, subprocesses or workflow state.
//! callers/tests: offline evaluator CLI; verification: path escapes, symlinks and bounded read parity.
use std::{
    ffi::CString,
    fs::{self, File, OpenOptions},
    io::{self, Read},
    os::unix::{
        fs::OpenOptionsExt,
        io::{AsRawFd, FromRawFd},
    },
    path::Path,
};

const MAX_BYTES: u64 = 65536;

pub(crate) struct BehaviorEvalArtifacts(File);

impl BehaviorEvalArtifacts {
    pub(crate) fn open(root: &str) -> Result<Self, String> {
        if root.is_empty() || root.contains('\0') {
            return Err("invalid artifact_root".into());
        }
        let path = Path::new(root);
        let inaccessible = || format!("inaccessible artifact_root: {root}");
        let metadata = fs::symlink_metadata(path).map_err(|_| inaccessible())?;
        if !metadata.is_dir() {
            return Err("artifact_root must be a non-symlink directory".into());
        }
        let dir = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(path)
            .map_err(|_| inaccessible())?;
        Ok(Self(dir))
    }

    pub(crate) fn failure(
        &self,
        provider: &str,
        case: &str,
        path: &str,
        expected: &str,
    ) -> Option<String> {
        Self::check(&self.0, provider, case, path, expected)
            .err()
            .map(|reason| format!("{reason}:{path}"))
    }

    fn check(
        root: &File,
        provider: &str,
        case: &str,
        path: &str,
        expected: &str,
    ) -> Result<(), &'static str> {
        let mut chars = path.chars();
        let drive = chars.next().is_some_and(char::is_alphabetic) && chars.next() == Some(':');
        let valid_component = |part: &str| {
            !part.is_empty() && !matches!(part, "." | "..") && !part.contains(['/', '\\', '\0'])
        };
        let parts = [provider, case]
            .into_iter()
            .chain(path.split('/'))
            .collect::<Vec<_>>();
        if drive || !parts.iter().all(|part| valid_component(part)) {
            return Err("artifact_path_escape");
        }
        let mut dir = None;
        for (index, part) in parts.iter().enumerate() {
            let parent = dir.as_ref().unwrap_or(root);
            let name = CString::new(*part).map_err(|_| "artifact_path_escape")?;
            let final_part = index + 1 == parts.len();
            let opened = Self::open_child(parent, &name, final_part)?;
            if final_part {
                return Self::compare(opened, expected);
            }
            dir = Some(opened);
        }
        Err("artifact_missing")
    }

    fn open_child(dir: &File, name: &CString, leaf: bool) -> Result<File, &'static str> {
        // Verify each component without dereferencing it. The subsequent
        // descriptor-relative NOFOLLOW open also covers a concurrent swap.
        let mut metadata = std::mem::MaybeUninit::<libc::stat>::uninit();
        let found = unsafe {
            libc::fstatat(
                dir.as_raw_fd(),
                name.as_ptr(),
                metadata.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        };
        if found != 0 {
            return Err(Self::path_error());
        }
        let kind = unsafe { metadata.assume_init() }.st_mode & libc::S_IFMT;
        match (kind, leaf) {
            (libc::S_IFLNK, _) => return Err("artifact_symlink_escape"),
            (libc::S_IFDIR, false) | (libc::S_IFREG, true) => {}
            (_, false) => return Err("artifact_missing"),
            (_, true) => return Err("artifact_unreadable"),
        }
        let mut flags = libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC;
        if !leaf {
            flags |= libc::O_DIRECTORY;
        }
        let fd = unsafe { libc::openat(dir.as_raw_fd(), name.as_ptr(), flags) };
        if fd < 0 {
            return Err(Self::path_error());
        }
        Ok(unsafe { File::from_raw_fd(fd) })
    }

    fn path_error() -> &'static str {
        match io::Error::last_os_error().raw_os_error() {
            Some(libc::ENOENT | libc::ENOTDIR) => "artifact_missing",
            Some(libc::ELOOP) => "artifact_symlink_escape",
            _ => "artifact_unreadable",
        }
    }

    fn compare(file: File, expected: &str) -> Result<(), &'static str> {
        if !file
            .metadata()
            .map_err(|_| "artifact_unreadable")?
            .is_file()
        {
            return Err("artifact_unreadable");
        }
        let mut bytes = Vec::new();
        file.take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "artifact_unreadable")?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err("artifact_unreadable");
        }
        if std::str::from_utf8(&bytes).map_err(|_| "artifact_unreadable")? != expected {
            return Err("artifact_mismatch");
        }
        Ok(())
    }
}
