//! owner: CliRender; allowed imports: std/libc terminal width; forbidden imports:
//! process spawning; callers/tests: NextCli; verification: argparse widths and exact text.
pub(super) struct CliRender;
impl CliRender {
    pub(super) fn plain_exit(stderr: bool) -> bool {
        let enabled = |name| std::env::var_os(name).is_some_and(|s| !s.is_empty());
        if env!("MORU_NEXT_ARGPARSE_COLOR") != "true" || enabled("NO_COLOR") {
            return true;
        }
        if enabled("FORCE_COLOR") {
            return false;
        }
        if std::env::var_os("TERM").is_some_and(|s| s == "dumb") {
            return true;
        }
        // Usage formatting may consult stdout even when the error goes to stderr.
        unsafe { libc::isatty(1) == 0 && (!stderr || libc::isatty(2) == 0) }
    }
    const PROG: &'static str = "agent_next_action.py";
    pub(super) fn width() -> Option<usize> {
        let env = std::env::var("COLUMNS").ok();
        if env
            .as_ref()
            .is_some_and(|v| !v.is_ascii() || v.contains('_'))
        {
            return None;
        }
        if let Some(raw) = env.as_ref() {
            let raw = raw.trim();
            let digits = raw.trim_start_matches(['+', '-']);
            if !digits.is_empty()
                && digits.bytes().all(|c| c.is_ascii_digit())
                && raw.parse::<i64>().is_err()
            {
                return None;
            }
        }
        let columns = env
            .and_then(|v| v.trim().parse::<i64>().ok())
            .filter(|n| *n > 0)
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
        let parts = [
            "[-h]",
            "[--project PROJECT]",
            "[--evidence EVIDENCE]",
            "[--format {markdown,json}]",
        ];
        let one = format!("usage: {} {}", Self::PROG, parts.join(" "));
        if one.len() <= width {
            return format!("{one}\n");
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
        for part in parts {
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
    fn wrap(text: &str, width: usize) -> Vec<String> {
        let mut lines = Vec::new();
        let mut line = String::new();
        for word in text.split_whitespace() {
            let mut word = word;
            if !line.is_empty() && line.len() + 1 + word.len() > width {
                if word.len() > width && line.len() + 1 < width {
                    let take = width - line.len() - 1;
                    line.push(' ');
                    line.push_str(&word[..take]);
                    word = &word[take..];
                }
                lines.push(std::mem::take(&mut line));
            }
            while word.len() > width {
                lines.push(word[..width].into());
                word = &word[width..];
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        if !line.is_empty() {
            lines.push(line);
        }
        lines
    }
    pub(super) fn help(width: usize) -> String {
        let mut out = Self::usage(width);
        out.push('\n');
        out.push_str(
            &Self::wrap(
                "Show the exact next lifecycle step and copyable command.",
                width.max(11),
            )
            .join("\n"),
        );
        out.push_str("\n\n");
        out.push_str(env!("MORU_ARGPARSE_OPTIONS_TITLE"));
        out.push('\n');
        let pos = 24.min(width.saturating_sub(20).max(4));
        let help_width = width.saturating_sub(pos).max(11);
        for (name, help) in [
            ("-h, --help", "show this help message and exit"),
            ("--project PROJECT", ""),
            ("--evidence EVIDENCE", "Explicit preflight.json path."),
            ("--format {markdown,json}", ""),
        ] {
            out.push_str("  ");
            out.push_str(name);
            if help.is_empty() {
                out.push('\n');
                continue;
            }
            if name.len() > pos.saturating_sub(4) {
                out.push('\n');
                out.push_str(&" ".repeat(pos));
            } else {
                out.push_str(&" ".repeat(pos - 2 - name.len()));
            }
            for (i, line) in Self::wrap(help, help_width).iter().enumerate() {
                if i > 0 {
                    out.push_str(&" ".repeat(pos));
                }
                out.push_str(line);
                out.push('\n');
            }
        }
        out
    }
}
