//! Text and path helpers matching Python str/pathlib behaviour used by the subject.

use std::fs;

/// One internal owner for the Python-compatible text/path operations.
pub struct Text;

impl Text {
    fn is_py_space(c: char) -> bool {
        c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
    }

    /// Python str.strip(): Unicode whitespace plus \x1c-\x1f.
    pub fn py_strip(s: &str) -> &str {
        s.trim_matches(Self::is_py_space)
    }

    /// Text-mode decoding in Python converts \r\n and \r to \n.
    pub fn universal_newlines(s: &str) -> String {
        s.replace("\r\n", "\n").replace('\r', "\n")
    }

    /// PurePosixPath string normalisation: duplicate slashes and "." segments
    /// vanish, ".." is kept, exactly two leading slashes are kept.
    pub fn norm_path(p: &str) -> String {
        let lead = p.bytes().take_while(|&b| b == b'/').count();
        let prefix = match lead {
            0 => "",
            2 => "//",
            _ => "/",
        };
        let parts: Vec<&str> = p
            .split('/')
            .filter(|s| !s.is_empty() && *s != ".")
            .collect();
        if parts.is_empty() {
            return if prefix.is_empty() {
                ".".to_string()
            } else {
                prefix.to_string()
            };
        }
        format!("{}{}", prefix, parts.join("/"))
    }

    /// base / rel, where an absolute rel replaces base.
    pub fn join_path(base: &str, rel: &str) -> String {
        if rel.starts_with('/') {
            Self::norm_path(rel)
        } else {
            Self::norm_path(&format!("{}/{}", base, rel))
        }
    }

    fn lexical_clean(p: &str) -> String {
        let rooted = p.starts_with('/');
        let mut stack: Vec<&str> = Vec::new();
        for seg in p.split('/') {
            match seg {
                "" | "." => {}
                ".." => {
                    if stack.last().map_or(false, |last| *last != "..") {
                        stack.pop();
                    } else if !rooted {
                        stack.push("..");
                    }
                }
                other => stack.push(other),
            }
        }
        let body = stack.join("/");
        if rooted {
            format!("/{}", body)
        } else if body.is_empty() {
            ".".to_string()
        } else {
            body
        }
    }

    /// Follows symlinks like Path.resolve(); an unresolvable path falls back to
    /// its lexical form.
    pub fn resolve(p: &str) -> String {
        match fs::canonicalize(p) {
            Ok(real) => real.to_string_lossy().into_owned(),
            Err(_) => Self::lexical_clean(p),
        }
    }

    pub fn is_dir(p: &str) -> bool {
        fs::metadata(p).map(|m| m.is_dir()).unwrap_or(false)
    }

    pub fn is_file(p: &str) -> bool {
        fs::metadata(p).map(|m| m.is_file()).unwrap_or(false)
    }
}
