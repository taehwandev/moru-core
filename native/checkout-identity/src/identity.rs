//! Port of the production disk-first checkout identity with git fallback.

use crate::gitrun;
use crate::metadata_text::MetadataText as Read;
use crate::text::Text;

#[derive(Clone, Copy)]
enum Resolution {
    Legacy,
    Strict,
}

impl Resolution {
    fn resolve(self, path: &str) -> Result<String, ()> {
        match self {
            Self::Legacy => Ok(Text::resolve(path)),
            // Path.resolve can retain an unresolved suffix, raise on symlink
            // loops, or return undecodable path bytes. Defer these to Python.
            Self::Strict => std::fs::canonicalize(path)
                .map_err(|_| ())?
                .into_os_string()
                .into_string()
                .map_err(|_| ()),
        }
    }

    fn objects_directory(self, path: &str) -> Result<bool, ()> {
        if matches!(self, Self::Legacy) {
            return Ok(Text::is_dir(path));
        }
        match std::fs::metadata(path) {
            Ok(meta) => Ok(meta.is_dir()),
            Err(error) if matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) => {
                Ok(false)
            }
            Err(_) => Err(()),
        }
    }
}

/// _checkout_git_dir: a .git directory, or a .git file naming one, whose HEAD
/// is a regular file.
fn checkout_git_dir(root: &str, mode: Resolution) -> Result<Option<String>, ()> {
    let marker = Text::join_path(root, ".git");
    let git_dir = if Text::is_dir(&marker) {
        marker
    } else if Text::is_file(&marker) {
        let text = match Read::load(&marker) {
            Read::Text(text) => text,
            _ => return Ok(None),
        };
        let Some(named) = Text::py_strip(&text).strip_prefix("gitdir:") else {
            return Ok(None);
        };
        let named = Text::py_strip(named);
        Text::join_path(root, named)
    } else {
        return Ok(None);
    };
    if !Text::is_file(&Text::join_path(&git_dir, "HEAD")) {
        return Ok(None);
    }
    mode.resolve(&git_dir).map(Some)
}

/// _common_dir_from_disk.
fn common_dir_from_disk(root: &str, mode: Resolution) -> Result<Option<String>, ()> {
    let git_dir = match checkout_git_dir(root, mode)? {
        Some(dir) => dir,
        None => return Ok(None),
    };
    let common = match Read::load(&Text::join_path(&git_dir, "commondir")) {
        Read::Missing => git_dir,
        Read::Bad => return Ok(None),
        Read::Text(text) => {
            let named = Text::py_strip(&text);
            if named.is_empty() {
                git_dir
            } else if named.contains('\0') {
                return Err(());
            } else {
                mode.resolve(&Text::join_path(&git_dir, named))?
            }
        }
    };
    Ok(
        if mode.objects_directory(&Text::join_path(&common, "objects"))? {
            Some(common)
        } else {
            None
        },
    )
}

fn git_common_dir(root: &str, mode: Resolution) -> Result<Option<String>, ()> {
    if let Some(common) = common_dir_from_disk(root, mode)? {
        return Ok(Some(common));
    }
    let out = match gitrun::GitRead::run(root, &["rev-parse", "--git-common-dir"])? {
        Some(out) => out,
        None => return Ok(None),
    };
    let named = Text::py_strip(&out);
    if named.is_empty() {
        return Ok(None);
    }
    mode.resolve(&Text::join_path(root, named)).map(Some)
}

fn current_branch(root: &str, mode: Resolution) -> Result<String, ()> {
    if common_dir_from_disk(root, mode)?.is_some() {
        if let Some(git_dir) = checkout_git_dir(root, mode)? {
            let head = match Read::load(&Text::join_path(&git_dir, "HEAD")) {
                Read::Text(text) => Text::py_strip(&text).to_string(),
                _ => String::new(),
            };
            if let Some(name) = head.strip_prefix("ref: refs/heads/") {
                return Ok(name.to_string());
            }
        }
    }
    Ok(
        match gitrun::GitRead::run(root, &["branch", "--show-current"])? {
            Some(out) => Text::py_strip(&out).to_string(),
            None => String::new(),
        },
    )
}

pub(super) struct Identity;

impl Identity {
    /// Common dir, then branch, each computed independently with no caching.
    pub(super) fn lookup(raw_root: &str) -> Result<(Option<String>, String), ()> {
        let root = Text::norm_path(raw_root);
        let common = git_common_dir(&root, Resolution::Legacy)?;
        let branch = current_branch(&root, Resolution::Legacy)?;
        Ok((common, branch))
    }

    pub(super) fn common_dir(root: &str) -> Result<Option<String>, ()> {
        git_common_dir(&Text::norm_path(root), Resolution::Strict)
    }

    pub(super) fn branch(root: &str) -> Result<String, ()> {
        current_branch(&Text::norm_path(root), Resolution::Strict)
    }
}
