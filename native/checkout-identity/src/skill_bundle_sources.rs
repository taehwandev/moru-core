//! Owner: flat skill guidance discovery. Allowed imports: filesystem metadata,
//! directory entries and JSON. Forbidden imports: file contents and mutations.
//! Callers/tests: source_docs probe and synthetic migration layout tests.
use serde_json::{json, Value};
use std::{fs, path::Path};

const MAX_ENTRIES: usize = 8192;
const MAX_PATH_BYTES: usize = 512 * 1024;

fn names(path: &Path, remaining: &mut usize) -> Option<Vec<String>> {
    let mut names = Vec::new();
    for item in fs::read_dir(path).ok()? {
        *remaining = remaining.checked_sub(1)?;
        names.push(item.ok()?.file_name().into_string().ok()?);
    }
    names.sort_unstable();
    Some(names)
}

fn is_dir(path: &Path) -> Option<bool> {
    match fs::metadata(path) {
        Ok(metadata) => Some(metadata.is_dir()),
        Err(err)
            if matches!(
                err.raw_os_error(),
                Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP)
            ) =>
        {
            Some(false)
        }
        Err(_) => None,
    }
}

struct Sources<'a> {
    root: &'a Path,
    remaining: usize,
    path_bytes: usize,
    sources: Vec<String>,
}

impl Sources<'_> {
    fn markdown(&mut self, relative: &Path) -> Option<()> {
        let dir = self.root.join(relative);
        if !is_dir(&dir)? {
            return Some(());
        }
        for name in names(&dir, &mut self.remaining)? {
            // Path.glob("*.md") includes dotfiles, symlinks and directories.
            if !name.ends_with(".md") || (relative == Path::new("workflows") && name == "README.md")
            {
                continue;
            }
            let file = relative.join(name);
            if self.root.join(&file).to_str()?.contains("/skills/") {
                continue;
            }
            let text = file.to_str()?;
            self.path_bytes = self
                .path_bytes
                .checked_add(serde_json::to_vec(text).ok()?.len() + 1)?;
            if self.path_bytes > MAX_PATH_BYTES {
                return None;
            }
            self.sources.push(text.to_owned());
        }
        Some(())
    }
}

pub(super) fn discover(request: &Value) -> Option<Value> {
    let raw = request.get("root")?.as_str()?;
    let root = Path::new(raw);
    if !root.is_absolute() || !root.is_dir() || root.canonicalize().ok()?.to_str()? != raw {
        return None;
    }
    let mut scan = Sources {
        root,
        remaining: MAX_ENTRIES,
        path_bytes: 0,
        sources: Vec::new(),
    };
    for group in ["common", "workflows", "product-patterns"] {
        scan.markdown(Path::new(group))?;
    }
    let platforms = Path::new("platforms");
    // Unlike the glob groups, platforms.iterdir() propagates missing-directory errors.
    for name in names(&root.join(platforms), &mut scan.remaining)? {
        scan.markdown(&platforms.join(name))?;
    }
    scan.markdown(Path::new("docs"))?;
    Some(json!({"sources": scan.sources}))
}
