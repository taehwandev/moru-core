//! owner: ArgparseHelp; allowed imports: std string and collection handling;
//! forbidden imports: I/O, environment and interpreter startup;
//! callers/tests: offline evaluator and overhead CLI; verification: argparse parity.

use std::collections::VecDeque;

pub(crate) struct ArgparseHelp;

impl ArgparseHelp {
    pub(crate) fn usage(prog: &str, parts: &[&str], width: usize) -> String {
        let single = format!("usage: {} {}", prog, parts.join(" "));
        if single.len() <= width {
            return single + "\n";
        }
        let mut out = format!("usage: {}", prog);
        let short = (7 + prog.len()) as f64 <= 0.75 * width as f64;
        let indent = if short { 8 + prog.len() } else { 7 };
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
    pub(crate) fn help(
        prog: &str,
        parts: &[&str],
        description: &str,
        title: &str,
        rows: &[(&str, &str)],
        width: usize,
    ) -> String {
        let mut out = Self::usage(prog, parts, width);
        out.push('\n');
        out.push_str(&Self::wrap(description, width).join("\n"));
        out.push_str("\n\n");
        out.push_str(title);
        out.push('\n');
        let position = 24.min(width.saturating_sub(20).max(4));
        let help_width = width.saturating_sub(position).max(11);
        for &(name, help) in rows {
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
            // Help descriptions are fixed ASCII. Match textwrap's word-internal hyphens.
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
