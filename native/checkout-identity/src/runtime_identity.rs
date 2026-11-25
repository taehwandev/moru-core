//! owner: runtime session selection; allowed imports: env, native process metadata, Python text;
//! forbidden imports: registry, mutation, process spawning; callers/tests: inferred loop status.
use crate::python_text::PythonText;
use std::env;

pub(crate) struct RuntimeIdentity;
impl RuntimeIdentity {
    pub(crate) fn current() -> Option<Option<(&'static str, String)>> {
        let claude = Self::value("CLAUDE_CODE_SESSION_ID")?;
        let codex = Self::value("CODEX_THREAD_ID")?;
        let agy = Self::value("ANTIGRAVITY_CONVERSATION_ID")?;
        let explicit = Self::value("MORU_AI_TOOL")?.to_lowercase();
        // The Python reference chooses the nearest recognized ancestor before
        // consulting launcher hints or inherited environment IDs.
        if let Some((runtime, pid_identity)) = Self::ancestor() {
            let id = match runtime {
                "claude" => &claude,
                "codex" => &codex,
                _ => &agy,
            };
            if !id.is_empty() {
                return Some(Some((runtime, id.clone())));
            }
            if runtime == "antigravity" {
                return Some(Some((runtime, pid_identity)));
            }
        }
        match explicit.as_str() {
            "claude" => return Some(Self::nonempty("claude", claude)),
            "codex" => return Some(Self::nonempty("codex", codex)),
            "antigravity" | "agy" => return Some(Self::nonempty("antigravity", agy)),
            "gemini" | "openai" => return Some(None),
            _ => {}
        }
        if !agy.is_empty() {
            return Some(Some(("antigravity", agy)));
        }
        if !codex.is_empty() {
            return Some(Some(("codex", codex)));
        }
        let agy_marker = Self::any_marker(&[
            "ANTIGRAVITY_AGENT",
            "ANTIGRAVITY_CLI_ALIAS",
            "ANTIGRAVITY_TRAJECTORY_ID",
        ])?;
        let codex_marker = Self::any_marker(&["CODEX_SANDBOX", "CODEX_CI"])?;
        if agy_marker && !codex_marker {
            return Some(None);
        }
        Some(Self::nonempty("claude", claude))
    }

    fn nonempty(runtime: &'static str, id: String) -> Option<(&'static str, String)> {
        (!id.is_empty()).then_some((runtime, id))
    }

    fn any_marker(keys: &[&str]) -> Option<bool> {
        for key in keys {
            if !Self::value(key)?.is_empty() {
                return Some(true);
            }
        }
        Some(false)
    }

    fn value(key: &str) -> Option<String> {
        match env::var(key) {
            Ok(raw) => Some(raw.trim_matches(PythonText::whitespace).into()),
            Err(env::VarError::NotPresent) => Some(String::new()),
            Err(_) => None,
        }
    }

    fn ancestor() -> Option<(&'static str, String)> {
        let mut pid = unsafe { libc::getppid() };
        for _ in 0..32 {
            if pid <= 1 {
                break;
            }
            let (parent, name, birth) = Self::process(pid)?;
            let runtime = match name.as_str() {
                "agy" | "agy-real" => "antigravity",
                "claude" => "claude",
                "codex" => "codex",
                _ => {
                    pid = parent;
                    continue;
                }
            };
            return Some((runtime, format!("pid-{pid}-{birth}")));
        }
        None
    }

    #[cfg(target_os = "macos")]
    fn process(pid: i32) -> Option<(i32, String, String)> {
        crate::darwin_process::DarwinParent::runtime_info(pid)
    }

    #[cfg(not(target_os = "macos"))]
    fn process(pid: i32) -> Option<(i32, String, String)> {
        let raw = std::fs::read(format!("/proc/{pid}/stat")).ok()?;
        let text = String::from_utf8_lossy(&raw);
        let (name, tail) = text.split_once('(')?.1.rsplit_once(')')?;
        let mut fields = tail.split_whitespace();
        let parent = fields.nth(1)?.parse().ok()?;
        let birth = fields.nth(17)?.to_owned();
        Some((parent, name.into(), birth))
    }
}
