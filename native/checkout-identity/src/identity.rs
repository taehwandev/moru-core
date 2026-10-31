//! Port of the production disk-first checkout identity with git fallback.

use crate::gitrun;
use crate::metadata_text::MetadataText as Read;
use crate::text::Text;

/// _checkout_git_dir: a .git directory, or a .git file naming one, whose HEAD
/// is a regular file.
fn checkout_git_dir(root: &str) -> Option<String> {
    let marker = Text::join_path(root, ".git");
    let git_dir = if Text::is_dir(&marker) {
        marker
    } else if Text::is_file(&marker) {
        let text = match Read::load(&marker) {
            Read::Text(text) => text,
            _ => return None,
        };
        let named = Text::py_strip(Text::py_strip(&text).strip_prefix("gitdir:")?);
        Text::join_path(root, named)
    } else {
        return None;
    };
    if !Text::is_file(&Text::join_path(&git_dir, "HEAD")) {
        return None;
    }
    Some(Text::resolve(&git_dir))
}

/// _common_dir_from_disk.
fn common_dir_from_disk(root: &str) -> Result<Option<String>, ()> {
    let git_dir = match checkout_git_dir(root) {
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
                Text::resolve(&Text::join_path(&git_dir, named))
            }
        }
    };
    Ok(if Text::is_dir(&Text::join_path(&common, "objects")) {
        Some(common)
    } else {
        None
    })
}

fn git_common_dir(root: &str) -> Result<Option<String>, ()> {
    if let Some(common) = common_dir_from_disk(root)? {
        return Ok(Some(common));
    }
    let out = match gitrun::run(root, &["rev-parse", "--git-common-dir"])? {
        Some(out) => out,
        None => return Ok(None),
    };
    let named = Text::py_strip(&out);
    if named.is_empty() {
        return Ok(None);
    }
    Ok(Some(Text::resolve(&Text::join_path(root, named))))
}

fn current_branch(root: &str) -> Result<String, ()> {
    if common_dir_from_disk(root)?.is_some() {
        if let Some(git_dir) = checkout_git_dir(root) {
            let head = match Read::load(&Text::join_path(&git_dir, "HEAD")) {
                Read::Text(text) => Text::py_strip(&text).to_string(),
                _ => String::new(),
            };
            if let Some(name) = head.strip_prefix("ref: refs/heads/") {
                return Ok(name.to_string());
            }
        }
    }
    Ok(match gitrun::run(root, &["branch", "--show-current"])? {
        Some(out) => Text::py_strip(&out).to_string(),
        None => String::new(),
    })
}

/// Common dir, then branch, each computed independently with no caching.
pub fn identity(raw_root: &str) -> Result<(Option<String>, String), ()> {
    let root = Text::norm_path(raw_root);
    let common = git_common_dir(&root)?;
    let branch = current_branch(&root)?;
    Ok((common, branch))
}
