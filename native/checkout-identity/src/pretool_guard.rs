//! Same-root, exact source and ordinary environment checks for native deferral.
use sha2::{Digest, Sha256};
use std::{
    env,
    ffi::OsStr,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

mod contract {
    include!(concat!(env!("OUT_DIR"), "/pretool_contract.rs"));
}

pub(crate) struct CallbackGuard;

impl CallbackGuard {
    pub(crate) fn root(launcher: &OsStr, executable: &str) -> Option<PathBuf> {
        let mut selected = None;
        validate(launcher, executable, &mut selected)
            .then_some(selected)
            .flatten()
    }
}

fn validate(launcher: &OsStr, executable: &str, selected_root: &mut Option<PathBuf>) -> bool {
    if !environment_ready() {
        return false;
    }
    let Some(base) = Path::new(launcher).parent().and_then(Path::parent) else {
        return false;
    };
    let Ok(pointer) = fs::read_to_string(base.join("moru-root")) else {
        return false;
    };
    let Ok(root) = Path::new(pointer.trim()).canonicalize() else {
        return false;
    };
    let selected = match env::var("MORU_HOME") {
        Ok(value) if !value.trim().is_empty() => Path::new(value.trim()).canonicalize(),
        Err(env::VarError::NotUnicode(_)) => return false,
        _ => {
            let Some(home) = env::var_os("HOME") else {
                return false;
            };
            if base.canonicalize().ok() != Path::new(&home).join(".moru").canonicalize().ok() {
                return false;
            }
            Ok(root.clone())
        }
    };
    if selected.ok() != Some(root.clone())
        || !["AGENTS.md", "index.md", "scripts/workflow.py"]
            .iter()
            .all(|p| root.join(p).is_file())
    {
        return false;
    }
    let Ok(cwd) = env::current_dir().and_then(fs::canonicalize) else {
        return false;
    };
    if !resolvable(&cwd.join(executable)) || !resolvable(Path::new(launcher)) {
        return false;
    }
    let Some(home) = env::var_os("HOME") else {
        return false;
    };
    if !Path::new(&home).is_absolute() {
        return false;
    }
    if !resolvable(&Path::new(&home).join(".moru/bin/moru-hook")) {
        return false;
    }
    for (relative, expected, size) in contract::SOURCES {
        if digest_file(&root.join(relative), *size)
            .as_ref()
            .map(|d| d.as_slice())
            != Some(*expected)
        {
            return false;
        }
    }
    let valid = contract::DIRECTORIES
        .iter()
        .all(|relative| source_directory_matches(&root, relative));
    if valid {
        *selected_root = Some(root);
    }
    valid
}

fn source_directory_matches(root: &Path, relative: &str) -> bool {
    let entries = match fs::read_dir(root.join(relative)) {
        Ok(entries) => entries,
        Err(_) => return false,
    };
    for entry in entries {
        let Ok(entry) = entry else { return false };
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            return false;
        };
        let path = format!("{relative}/{name}");
        let Ok(kind) = entry.file_type() else {
            return false;
        };
        if kind.is_dir() && contract::CACHES.binary_search(&name).is_ok() {
            continue;
        }
        if kind.is_dir() && contract::DIRECTORIES.binary_search(&path.as_str()).is_err() {
            return false;
        }
        if kind.is_symlink() && entry.path().is_dir() {
            return false;
        }
        if name.ends_with(".py")
            && contract::SOURCES
                .binary_search_by(|(p, _, _)| p.cmp(&path.as_str()))
                .is_err()
        {
            return false;
        }
        if [".pyc", ".pyo", ".so", ".pyd", ".dll", ".dylib"]
            .iter()
            .any(|suffix| name.ends_with(suffix))
        {
            return false;
        }
    }
    true
}

fn environment_ready() -> bool {
    for (key, value) in env::vars_os() {
        let key = key.to_string_lossy();
        if key.starts_with("PYTHON") || key.starts_with("_PYTHON") {
            match key.as_ref() {
                "PYTHONDONTWRITEBYTECODE" | "PYTHONPYCACHEPREFIX" => {}
                "PYTHONUTF8" if value == "1" => {}
                _ => return false,
            }
        }
    }
    for key in ["MORU_STATE_HOME", "CLAUDE_PROJECT_DIR", "CODEX_PROJECT_DIR"] {
        match env::var(key) {
            Ok(value) => {
                let value = crate::statusline::Renderer::strip(&value);
                if !value.is_empty()
                    && (!Path::new(value).is_absolute() || !resolvable(Path::new(value)))
                {
                    return false;
                }
            }
            Err(env::VarError::NotUnicode(_)) => return false,
            Err(env::VarError::NotPresent) => {}
        }
    }
    true
}

fn digest_file(path: &Path, expected: u64) -> Option<[u8; 32]> {
    let mut file = fs::File::open(path).ok()?.take(expected + 1);
    let mut buffer = [0; 16 * 1024];
    let mut size = 0;
    let mut hash = Sha256::new();
    loop {
        let count = file.read(&mut buffer).ok()?;
        if count == 0 {
            break;
        }
        size += count as u64;
        hash.update(&buffer[..count]);
    }
    (size == expected).then(|| hash.finalize().into())
}

fn resolvable(path: &Path) -> bool {
    match fs::symlink_metadata(path) {
        Ok(_) => path.canonicalize().is_ok(),
        Err(error) => error.kind() == std::io::ErrorKind::NotFound,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_backend_matches_standard_vectors() {
        for (input, expected) in [
            (
                "",
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            ),
            (
                "abc",
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            ),
            (
                "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
                "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
            ),
        ] {
            assert_eq!(format!("{:x}", Sha256::digest(input.as_bytes())), expected);
        }
    }

    #[test]
    fn sha256_streaming_backend_matches_multiblock_vector() {
        let input = vec![b'a'; 1_000_000];
        let mut hash = Sha256::new();
        for chunk in input.chunks(17) {
            hash.update(chunk);
        }
        assert_eq!(
            format!("{:x}", hash.finalize()),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }
}
