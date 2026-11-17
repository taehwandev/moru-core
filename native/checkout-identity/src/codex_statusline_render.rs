//! Private minimal text edits for CodexStatusLine; preserves uninterpreted bytes.
use super::CodexStatusLine;
impl CodexStatusLine {
    pub(super) fn append(text: &str, opening: usize, closing: usize, items: &[&str]) -> String {
        let mut body = text[opening + 1..closing].to_owned();
        let last = Self::last_syntax(&body);
        if let Some(end) = last {
            if body.as_bytes()[end - 1] != b',' {
                body.insert(end, ',');
            }
        }
        let rendered = items
            .iter()
            .map(|item| format!("\"{item}\""))
            .collect::<Vec<_>>()
            .join(", ");
        body = if let Some((core, closing_indent)) = body
            .rsplit_once('\n')
            .filter(|(_, tail)| Self::strip(tail).is_empty())
        {
            let indentation = Self::indent(core, closing_indent);
            format!(
                "{core}{}{indentation}{rendered}\n{closing_indent}",
                if core.ends_with('\n') { "" } else { "\n" }
            )
        } else {
            format!("{body}{}{rendered}", if last.is_none() { "" } else { " " })
        };
        format!("{}{body}{}", &text[..opening + 1], &text[closing..])
    }

    fn indent(core: &str, closing: &str) -> String {
        // str.splitlines includes Unicode line/paragraph separators and C0 separators.
        let lines: Vec<_> = core
            .split([
                '\n', '\r', '\u{b}', '\u{c}', '\u{1c}', '\u{1d}', '\u{1e}', '\u{85}', '\u{2028}',
                '\u{2029}',
            ])
            .collect();
        for line in lines.into_iter().rev() {
            if !Self::strip(line).is_empty()
                && !line.trim_start_matches(Self::space).starts_with('#')
            {
                return line[..line.len() - line.trim_start_matches(Self::space).len()].into();
            }
        }
        format!("{closing}  ")
    }

    pub(super) fn insert(text: &str, headers: &[(usize, usize, &str)]) -> Option<String> {
        const ARRAY: &str =
            "[\"model-with-reasoning\", \"current-dir\", \"five-hour-limit\", \"weekly-limit\"]";
        if let Some((_, end, _)) = headers
            .iter()
            .find(|(_, _, name)| Self::strip(name) == "tui")
        {
            let line_end = text[*end..].find('\n').map(|index| end + index);
            let insertion = line_end.map_or(text.len(), |end| end + 1);
            return Some(format!(
                "{}{}status_line = {ARRAY}\n{}",
                &text[..insertion],
                if line_end.is_none() { "\n" } else { "" },
                &text[insertion..]
            ));
        }
        let first = headers.first().map_or(text.len(), |h| h.0);
        if !Self::assignments(&text[..first], "tui").is_empty() {
            return None;
        }
        if headers
            .iter()
            .any(|(_, _, name)| Self::strip(name).starts_with("tui."))
        {
            return Some(format!(
                "{}tui.status_line = {ARRAY}\n{}",
                &text[..first],
                &text[first..]
            ));
        }
        let separator = if text.is_empty() {
            ""
        } else if text.ends_with('\n') {
            "\n"
        } else {
            "\n\n"
        };
        Some(format!("{text}{separator}[tui]\nstatus_line = {ARRAY}\n"))
    }
}
