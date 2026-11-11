//! owner: OverheadCliHelp; allowed imports: std and libc terminal width query;
//! forbidden imports: file/provider/state reads; callers/tests: OverheadCli;
//! verification: builder argparse help layout, narrow widths and hyphen wrapping.
use std::collections::VecDeque;
pub(super) struct OverheadCliHelp;
impl OverheadCliHelp {
    const PROG: &'static str = "moru_overhead_report.py";
    const PARTS: [&'static str; 13] = [
        "[-h]",
        "[--days DAYS]",
        "[--since SINCE]",
        "[--until UNTIL]",
        "[--projects-dir PROJECTS_DIR]",
        "[--timings TIMINGS]",
        "[--moru-root MORU_ROOT]",
        "[--alias-root ALIAS_ROOT]",
        "[--exclude-session EXCLUDE_SESSION]",
        "[--include-subagents]",
        "[--min-turns MIN_TURNS]",
        "[--out OUT]",
        "[--md MD]",
    ];
    pub(super) fn width() -> Option<usize> {
        // Newer argparse can color both help and errors. Preserve that path
        // before emitting anything until native ANSI formatting is owned here.
        let no_color = std::env::var_os("NO_COLOR").is_some_and(|value| !value.is_empty());
        if env!("MORU_ARGPARSE_SHORT_HELP") == "eager"
            && !no_color
            && (std::env::var_os("FORCE_COLOR").is_some()
                || unsafe { libc::isatty(1) == 1 || libc::isatty(2) == 1 })
        {
            return None;
        }
        let value = match std::env::var("COLUMNS") {
            Ok(value) => Some(value),
            Err(std::env::VarError::NotPresent) => None,
            Err(_) => return None,
        };
        if value
            .as_ref()
            .is_some_and(|v| !v.is_ascii() || v.contains('_'))
        {
            return None;
        }
        if value.as_ref().is_some_and(|v| {
            let token = v.trim();
            let digits = token.strip_prefix(['+', '-']).unwrap_or(token);
            !digits.is_empty()
                && digits.bytes().all(|b| b.is_ascii_digit())
                && token.parse::<i64>().is_err()
        }) {
            return None;
        }
        let columns = value
            .and_then(|v| v.trim().parse::<i64>().ok())
            .filter(|v| *v > 0)
            .unwrap_or_else(|| {
                let mut size: libc::winsize = unsafe { std::mem::zeroed() };
                if unsafe { libc::ioctl(1, libc::TIOCGWINSZ, &mut size) } == 0 && size.ws_col > 0 {
                    i64::from(size.ws_col)
                } else {
                    80
                }
            });
        (columns > 2 && columns <= 10000).then_some(columns as usize - 2)
    }
    pub(super) fn usage(width: usize) -> String {
        let single = format!("usage: {} {}", Self::PROG, Self::PARTS.join(" "));
        if single.len() <= width {
            return single + "\n";
        }
        let mut out = format!("usage: {}", Self::PROG);
        let short = (7 + Self::PROG.len()) as f64 <= 0.75 * width as f64;
        let indent = if short { 8 + Self::PROG.len() } else { 7 };
        let mut length = out.len();
        let mut has_part = short;
        if !short {
            out.push('\n');
            out.push_str(&" ".repeat(indent));
            length = indent;
        }
        for part in Self::PARTS {
            if has_part && length + 1 + part.len() > width {
                out.push('\n');
                out.push_str(&" ".repeat(indent));
                length = indent;
                has_part = false;
            }
            if has_part {
                out.push(' ');
                length += 1;
            }
            out.push_str(part);
            length += part.len();
            has_part = true;
        }
        out.push('\n');
        out
    }
    pub(super) fn help(width: usize) -> String {
        let mut out = Self::usage(width);
        out.push('\n');
        out.push_str(
            &Self::wrap(
                "Report Moru workflow overhead across local Claude Code sessions.",
                width,
            )
            .join("\n"),
        );
        out.push_str("\n\n");
        out.push_str(option_env!("MORU_ARGPARSE_OPTIONS_TITLE").unwrap_or("optional arguments:"));
        out.push('\n');
        let position = 24.min(width.saturating_sub(20).max(4));
        let help_width = width.saturating_sub(position).max(11);
        let names = [
            "-h, --help",
            "--days DAYS",
            "--since SINCE",
            "--until UNTIL",
            "--projects-dir PROJECTS_DIR",
            "--timings TIMINGS",
            "--moru-root MORU_ROOT",
            "--alias-root ALIAS_ROOT",
            "--exclude-session EXCLUDE_SESSION",
            "--include-subagents",
            "--min-turns MIN_TURNS",
            "--out OUT",
            "--md MD",
        ];
        for (index, name) in names.into_iter().enumerate() {
            let help = match index {
                0 => "show this help message and exit",
                7 => "another checkout path counted as moru-core, such as a pre-rename path",
                _ => "",
            };
            out.push_str("  ");
            out.push_str(name);
            if help.is_empty() {
                out.push('\n');
                continue;
            }
            if name.len() > position.saturating_sub(4) {
                out.push('\n');
                out.push_str(&" ".repeat(position));
            } else {
                out.push_str(&" ".repeat(position - 2 - name.len()));
            }
            for (index, line) in Self::wrap(help, help_width).iter().enumerate() {
                if index > 0 {
                    out.push_str(&" ".repeat(position));
                }
                out.push_str(line);
                out.push('\n');
            }
        }
        out
    }
    fn wrap(text: &str, width: usize) -> Vec<String> {
        let mut chunks = VecDeque::new();
        for (index, word) in text.split_whitespace().enumerate() {
            if index > 0 {
                chunks.push_back(" ".to_owned());
            }
            // Both help paragraphs are fixed ASCII. These are textwrap's
            // breakable word-internal hyphens in moru-core and pre-rename.
            let mut start = 0;
            for (at, _) in word.match_indices('-') {
                if at >= 2 && word.len() - at - 1 >= 2 {
                    chunks.push_back(word[start..=at].to_owned());
                    start = at + 1;
                }
            }
            if start < word.len() {
                chunks.push_back(word[start..].to_owned());
            }
        }
        let mut lines = Vec::new();
        while !chunks.is_empty() {
            while chunks.front().is_some_and(|v| v == " ") {
                chunks.pop_front();
            }
            let mut line = String::new();
            while chunks
                .front()
                .is_some_and(|v| line.len() + v.len() <= width)
            {
                line.push_str(&chunks.pop_front().unwrap());
            }
            if chunks.front().is_some_and(|v| v.len() > width) {
                let take = width - line.len();
                if take > 0 {
                    let chunk = chunks.front_mut().unwrap();
                    line.push_str(&chunk[..take]);
                    chunk.drain(..take);
                }
            }
            while line.ends_with(' ') {
                line.pop();
            }
            if !line.is_empty() {
                lines.push(line);
            }
        }
        lines
    }
}
