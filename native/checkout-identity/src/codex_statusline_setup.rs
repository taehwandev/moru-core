//! owner: Codex statusline standalone file setup; allowed imports: guarded local file I/O,
//! existing merge and launcher guards; forbidden imports: providers, other config or install;
//! callers/tests: launcher alias and synthetic-home parity.
use super::CodexStatusLine;
use crate::{pretool_guard::CallbackGuard, python_encoding::PythonEncoding, text::Text};
use std::{
    env,
    ffi::OsString,
    fs,
    io::{self, Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Path, PathBuf},
};

impl CodexStatusLine {
    pub(crate) fn setup(launcher: &OsString, args: &[OsString]) -> Option<i32> {
        const USAGE: &str = "usage: moru-hook codex-statusline-setup";
        if !args.is_empty() {
            if args.len() == 1 && (args[0] == "--help" || args[0] == "-h") {
                println!("{USAGE}");
                return Some(0);
            }
            eprintln!("{USAGE}");
            return Some(2);
        }
        if !PythonEncoding::utf8()
            || CallbackGuard::root(launcher, "codex-statusline-setup").is_none()
        {
            return None;
        }
        let home = env::var("HOME").ok()?;
        if home.starts_with("//") {
            return None;
        }
        let home: PathBuf = Path::new(&home).components().collect();
        let directory = home.join(".codex");
        if fs::symlink_metadata(&directory).is_ok_and(|meta| meta.file_type().is_symlink()) {
            return None;
        }
        let target = directory.join("config.toml");
        let (before, original) = Self::read_config(&target)?;
        let (mut status, updated) = Self::merge(&original);
        if status == "changed" {
            // Any failure after applying begins is final. A Python retry could
            // overwrite a concurrent change or replay a partial write.
            if let Err(error) = Self::write_config(&directory, &target, before.as_ref(), &updated) {
                eprintln!("Codex quota status line: {}: {error}", target.display());
                return Some(1);
            }
            status = "installed";
        }
        println!("Codex quota status line: {status} ({})", target.display());
        Some(i32::from(status == "missing"))
    }

    fn read_config(path: &Path) -> Option<(Option<fs::Metadata>, String)> {
        const LIMIT: u64 = 1024 * 1024;
        let before = match fs::symlink_metadata(path) {
            Ok(meta) => meta,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                return Some((None, String::new()));
            }
            Err(_) => return None,
        };
        if !before.is_file() || before.len() > LIMIT || before.nlink() != 1 {
            return None;
        }
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY)
            .open(path)
            .ok()?;
        if !Self::same_config(&before, &file.metadata().ok()?) {
            return None;
        }
        let mut bytes = Vec::new();
        (&file).take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > LIMIT || !Self::same_config(&before, &file.metadata().ok()?) {
            return None;
        }
        let text = std::str::from_utf8(&bytes).ok()?;
        Some((Some(before), Text::universal_newlines(text)))
    }

    fn write_config(
        directory: &Path,
        path: &Path,
        before: Option<&fs::Metadata>,
        text: &str,
    ) -> io::Result<()> {
        let mut open = fs::OpenOptions::new();
        open.write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_NOCTTY);
        let mut file = if let Some(before) = before {
            let file = open.open(path)?;
            if !Self::same_config(before, &file.metadata()?)
                || !Self::same_config(before, &fs::symlink_metadata(path)?)
            {
                return Err(io::Error::other("config changed during setup"));
            }
            file.set_len(0)?;
            file
        } else {
            fs::create_dir_all(directory)?;
            open.create_new(true).open(path)?
        };
        file.write_all(text.as_bytes())
    }

    fn same_config(a: &fs::Metadata, b: &fs::Metadata) -> bool {
        a.dev() == b.dev()
            && a.ino() == b.ino()
            && a.mode() == b.mode()
            && a.nlink() == b.nlink()
            && a.len() == b.len()
            && a.mtime() == b.mtime()
            && a.mtime_nsec() == b.mtime_nsec()
            && a.ctime() == b.ctime()
            && a.ctime_nsec() == b.ctime_nsec()
    }
}
