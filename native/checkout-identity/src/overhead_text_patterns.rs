//! owner: Patterns; allowed imports: Python whitespace and parent helpers;
//! forbidden imports: regex dependencies, command execution; callers/tests: OverheadText;
//! verification: ASCII word boundaries with conservative Unicode-word deferral.
use crate::python_text::PythonText;
const KNOWN: &[&str] = &[
    "start",
    "gate-batch",
    "gate",
    "review",
    "finish",
    "checkpoint",
    "next",
    "cancel",
    "fingerprint",
    "handoff",
    "resume",
    "agent-mailbox",
    "project-memory",
    "repair-verify",
    "setup-agent-hooks",
    "work-cards",
    "skill-feedback",
    "status",
    "doctor",
    "approval-record",
    "continuation",
    "skill-review",
    "claude-pretool-gate",
    "claude-stop-gate",
    "workflow",
];
pub(super) struct Patterns;
impl Patterns {
    pub(super) fn word(c: char) -> Option<bool> {
        if c.is_ascii() {
            Some(c.is_ascii_alphanumeric() || c == '_')
        } else if PythonText::whitespace(c) {
            Some(false)
        } else {
            None
        }
    }
    pub(super) fn word_before(chars: &[char], at: usize) -> Option<bool> {
        if at == 0 {
            Some(false)
        } else {
            Self::word(chars[at - 1])
        }
    }
    pub(super) fn word_after(chars: &[char], at: usize) -> Option<bool> {
        chars
            .get(at)
            .copied()
            .map(Self::word)
            .unwrap_or(Some(false))
    }
    fn starts(chars: &[char], at: usize, text: &str) -> bool {
        chars[at..]
            .iter()
            .copied()
            .take(text.len())
            .eq(text.chars())
    }
    fn spaces(chars: &[char], at: &mut usize) {
        while chars.get(*at).is_some_and(|c| PythonText::whitespace(*c)) {
            *at += 1;
        }
    }
    fn token(chars: &[char], at: &mut usize) -> Option<Option<String>> {
        if !chars.get(*at).is_some_and(char::is_ascii_alphabetic) {
            return Some(None);
        }
        let begin = *at;
        *at += 1;
        while *at < chars.len() && (chars[*at] == '-' || Self::word(chars[*at])?) {
            *at += 1;
        }
        Some(Some(chars[begin..*at].iter().collect()))
    }
    pub(super) fn launcher(text: &str, known: bool) -> Option<Option<String>> {
        let chars: Vec<char> = text.chars().collect();
        for begin in 0..chars.len() {
            for name in ["moru-hook", "agent-hook", "tao-hook"] {
                if !Self::starts(&chars, begin, name) {
                    continue;
                }
                let mut at = begin + name.len();
                if matches!(chars.get(at), Some('\'' | '"')) {
                    at += 1;
                }
                let space = at;
                Self::spaces(&chars, &mut at);
                if at == space {
                    continue;
                }
                let Some(sub) = Self::token(&chars, &mut at)? else {
                    continue;
                };
                let space = at;
                Self::spaces(&chars, &mut at);
                let second = if at > space {
                    Self::token(&chars, &mut at)?
                } else {
                    None
                };
                if sub == "workflow" {
                    if let Some(second) = second {
                        return Some(Some(format!("workflow {second}")));
                    }
                }
                return Some(Some(if !known || KNOWN.contains(&sub.as_str()) {
                    sub
                } else {
                    "other".into()
                }));
            }
        }
        Some(None)
    }
    pub(super) fn mark(text: &str) -> Option<bool> {
        if super::OverheadText::launcher_mark(text) || text.contains("Agent OS") {
            return Some(true);
        }
        let chars: Vec<char> = text.chars().collect();
        for at in 0..chars.len() {
            for label in ["Moru", "Tao"] {
                if Self::starts(&chars, at, label)
                    && !Self::word_before(&chars, at)?
                    && !Self::word_after(&chars, at + label.len())?
                {
                    return Some(true);
                }
            }
        }
        Some(false)
    }
    pub(super) fn note(text: &str) -> bool {
        let folded: String = text
            .chars()
            .map(|c| match c {
                'İ' | 'ı' => 'i',
                'ſ' => 's',
                'K' => 'k',
                _ => c.to_ascii_lowercase(),
            })
            .collect();
        folded.contains("policy note") || folded.contains("worktree gate")
    }
    pub(super) fn search(text: &str) -> Option<bool> {
        let chars: Vec<char> = text.chars().collect();
        let mut at = 0;
        Self::spaces(&chars, &mut at);
        for name in ["grep", "rg", "echo"] {
            if Self::starts(&chars, at, name) && !Self::word_after(&chars, at + name.len())? {
                return Some(true);
            }
        }
        if Self::starts(&chars, at, "git") {
            at += 3;
            let before = at;
            Self::spaces(&chars, &mut at);
            if at > before {
                for name in ["log", "grep", "diff"] {
                    if Self::starts(&chars, at, name) && !Self::word_after(&chars, at + name.len())?
                    {
                        return Some(true);
                    }
                }
            }
        }
        Some(false)
    }
    pub(super) fn guidance(text: &str) -> Option<bool> {
        let chars: Vec<char> = text.chars().collect();
        for at in 0..chars.len() {
            for reader in ["cat", "sed", "head", "tail", "less", "awk"] {
                if !Self::starts(&chars, at, reader) {
                    continue;
                }
                if Self::word_before(&chars, at)? || Self::word_after(&chars, at + reader.len())? {
                    continue;
                }
                let tail: String = chars[at + reader.len()..].iter().collect();
                for (begin, _) in tail.match_indices("moru-core") {
                    if tail[..begin].contains(['|', ';', '&']) {
                        break;
                    }
                    let candidate: String = tail[begin..]
                        .chars()
                        .take_while(|c| !PythonText::whitespace(*c) && !"'\"".contains(*c))
                        .collect();
                    for directory in ["/common/", "/workflows/", "/docs/", "/platforms/"] {
                        for (start, _) in candidate.match_indices(directory) {
                            if candidate[start + directory.len()..]
                                .match_indices(".md")
                                .any(|(pos, _)| pos > 0)
                            {
                                return Some(true);
                            }
                        }
                    }
                }
            }
        }
        Some(false)
    }
    pub(super) fn denial(text: &str) -> Option<&str> {
        let Some(tail) = text.strip_prefix("PreToolUse:") else {
            return Some(text);
        };
        let mut length = 0;
        for c in tail.chars() {
            if !Self::word(c)? {
                break;
            }
            length += c.len_utf8();
        }
        if length == 0 {
            return Some(text);
        }
        if let Some(rest) = tail[length..].strip_prefix(" hook error:") {
            Some(rest.trim_start_matches(PythonText::whitespace))
        } else {
            Some(text)
        }
    }
}
