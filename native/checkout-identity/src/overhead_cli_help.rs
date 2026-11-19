//! owner: OverheadCliHelp; allowed imports: std and libc terminal width query;
//! forbidden imports: file/provider/state reads; callers/tests: OverheadCli;
//! verification: builder argparse help layout, narrow widths and hyphen wrapping.
use crate::argparse_help::ArgparseHelp;
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
        ArgparseHelp::usage(Self::PROG, &Self::PARTS, width)
    }
    pub(super) fn help(width: usize) -> String {
        let rows = [
            ("-h, --help", "show this help message and exit"),
            ("--days DAYS", ""),
            ("--since SINCE", ""),
            ("--until UNTIL", ""),
            ("--projects-dir PROJECTS_DIR", ""),
            ("--timings TIMINGS", ""),
            ("--moru-root MORU_ROOT", ""),
            (
                "--alias-root ALIAS_ROOT",
                "another checkout path counted as moru-core, such as a pre-rename path",
            ),
            ("--exclude-session EXCLUDE_SESSION", ""),
            ("--include-subagents", ""),
            ("--min-turns MIN_TURNS", ""),
            ("--out OUT", ""),
            ("--md MD", ""),
        ];
        ArgparseHelp::help(
            Self::PROG,
            &Self::PARTS,
            "Report Moru workflow overhead across local Claude Code sessions.",
            option_env!("MORU_ARGPARSE_OPTIONS_TITLE").unwrap_or("optional arguments:"),
            &rows,
            width,
        )
    }
}
