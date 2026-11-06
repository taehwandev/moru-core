//! owner: OverheadProcess; allowed imports: source guard, session tally, std/JSON;
//! forbidden imports: providers, transcript writes, mutable shared state;
//! callers/tests: NativeOverhead; verification: synthetic protocol and fallback parity.
use crate::{overhead_session::OverheadSession, pretool_guard::CallbackGuard, text::Text};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    fs,
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    path::{Component, Path, PathBuf},
};

pub(crate) struct OverheadProcess;
impl OverheadProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || args[1] != "session"
            || CallbackGuard::root(launcher, "overhead-probe").is_none()
        {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        let result = serde_json::from_slice::<Value>(&bytes)
            .ok()
            .and_then(|v| Self::measure(&v));
        let Some(result) = result else {
            return 125;
        };
        let Ok(mut output) = serde_json::to_vec(&json!({"schema_version":1,"result":result}))
        else {
            return 125;
        };
        output.push(b'\n');
        if output.len() > 1024 * 1024 {
            return 125;
        }
        if std::io::stdout().write_all(&output).is_ok() {
            0
        } else {
            1
        }
    }
    fn measure(payload: &Value) -> Option<Value> {
        let path = payload.get("path")?.as_str()?;
        let roots = payload
            .get("roots")?
            .as_array()?
            .iter()
            .map(|v| v.as_str().map(str::to_owned))
            .collect::<Option<Vec<_>>>()?;
        let window = payload.get("window")?.as_array()?;
        if window.len() != 2 {
            return None;
        }
        let bytes = Self::read(path)?;
        let text = Text::universal_newlines(&String::from_utf8_lossy(&bytes));
        OverheadSession::measure(path, &text, &roots, window)
    }
    fn read(path: &str) -> Option<Vec<u8>> {
        const LIMIT: u64 = 64 * 1024 * 1024;
        if path.is_empty() || path.ends_with('/') {
            return None;
        }
        let original = Path::new(path);
        let absolute = if original.is_absolute() {
            original.to_owned()
        } else {
            std::env::current_dir().ok()?.join(original)
        };
        // Refuse every symlink and descriptor component before opening. A private
        // probe must never consume a stream and then ask Python to replay it.
        let mut prefix = PathBuf::new();
        for component in absolute.components() {
            if component == Component::ParentDir {
                return None;
            }
            prefix.push(component.as_os_str());
            if prefix == Path::new("/dev") || prefix == Path::new("/proc") {
                return None;
            }
            if fs::symlink_metadata(&prefix).ok()?.file_type().is_symlink() {
                return None;
            }
        }
        let before = fs::metadata(&absolute).ok()?;
        if !before.is_file() || before.len() > LIMIT {
            return None;
        }
        let file = fs::OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(&absolute)
            .ok()?;
        let opened = file.metadata().ok()?;
        if !opened.is_file() || !Self::same(&before, &opened) {
            return None;
        }
        let mut bytes = Vec::new();
        (&file).take(LIMIT + 1).read_to_end(&mut bytes).ok()?;
        if bytes.len() as u64 > LIMIT
            || !Self::same(&opened, &file.metadata().ok()?)
            || !Self::same(&opened, &fs::metadata(&absolute).ok()?)
        {
            return None;
        }
        Some(bytes)
    }
    fn same(a: &fs::Metadata, b: &fs::Metadata) -> bool {
        a.dev() == b.dev()
            && a.ino() == b.ino()
            && a.mode() == b.mode()
            && a.len() == b.len()
            && a.mtime() == b.mtime()
            && a.mtime_nsec() == b.mtime_nsec()
            && a.ctime() == b.ctime()
            && a.ctime_nsec() == b.ctime_nsec()
    }
}
