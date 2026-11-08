//! owner: OverheadReportText; allowed imports: serde_json, PythonJson Number, std;
//! forbidden imports: I/O, runtime Python, providers; callers/tests: overhead report CLI;
//! verification: JSON/Markdown formatting parity with synthetic reports.
use crate::python_json::Number;
use serde_json::Value;

pub(crate) struct OverheadReportText;

impl OverheadReportText {
    pub(crate) fn json(report: &Value) -> Option<String> {
        let mut text = String::new();
        Self::write_json(report, 0, true, false, &mut text)?;
        Some(text)
    }

    pub(crate) fn markdown(report: &Value) -> Option<String> {
        let window = report.get("window")?.as_object()?;
        let mut lines = vec![
            "# Moru workflow overhead".into(),
            String::new(),
            format!("Generated: {}  ", report.get("generated_at")?.as_str()?),
            format!(
                "Window: {} .. {}",
                window.get("since")?.as_str()?,
                window.get("until")?.as_str()?
            ),
            String::new(),
            format!(
                "Sessions: all={}, moru-core={}, other={}",
                Self::sessions(report, "all")?,
                Self::sessions(report, "moru_core")?,
                Self::sessions(report, "other_projects")?
            ),
            String::new(),
        ];
        for group in ["all", "moru_core", "other_projects"] {
            Self::group(report.get(group)?, group, &mut lines)?;
        }
        lines.extend([
            "## Moru hook latency from transcripts (ms)".into(),
            String::new(),
            "| hook | n | median | p90 |".into(),
            "|---|---|---|---|".into(),
        ]);
        for (key, value) in report
            .get("moru_hook_latency_ms_from_transcripts")?
            .as_object()?
        {
            let stats = value.as_object()?;
            lines.push(format!(
                "| {key} | {} | {} | {} |",
                Self::display(stats.get("n"))?,
                Self::display(stats.get("median"))?,
                Self::display(stats.get("p90"))?
            ));
        }
        for (title, key) in [
            ("Top policy notes", "top_policy_notes"),
            ("Top hook denials", "top_hook_denials"),
        ] {
            lines.extend([String::new(), format!("## {title}"), String::new()]);
            for (index, item) in report.get(key)?.as_array()?.iter().enumerate() {
                lines.push(format!(
                    "{}. ({}) {}",
                    index + 1,
                    Self::number(item.get("count")?.as_number()?)?,
                    item.get("message")?.as_str()?
                ));
            }
        }
        Some(lines.join("\n") + "\n")
    }

    fn sessions(report: &Value, name: &str) -> Option<u64> {
        report.get(name)?.get("sessions")?.as_u64()
    }

    fn group(data: &Value, name: &str, lines: &mut Vec<String>) -> Option<()> {
        let data = data.as_object()?;
        lines.extend([
            format!("## {name} (median / p90 per session)"),
            String::new(),
            "| metric | median | p90 | n |".into(),
            "|---|---|---|---|".into(),
        ]);
        for (label, key) in [
            ("assistant turns", "assistant_turns"),
            ("tool calls", "tool_calls"),
            ("lifecycle (launcher) Bash calls", "lifecycle_total"),
            ("policy notes", "policy_notes"),
            ("hook denials (all)", "hook_denials"),
            ("Moru hook denials", "moru_hook_denials"),
            ("guidance doc Reads", "guidance_reads"),
            ("guidance doc Bash reads", "guidance_bash_reads"),
            ("total tokens", "tok_total"),
            ("output tokens", "tok_output"),
            ("Moru-injected tokens (chars/4)", "moru_injected_tokens_est"),
        ] {
            let stats = match data.get(key) {
                None | Some(Value::Null) => None,
                Some(Value::Object(stats)) => Some(stats),
                _ => return None,
            };
            let field = |key| stats.and_then(|stats| stats.get(key));
            lines.push(format!(
                "| {label} | {} | {} | {} |",
                Self::display(field("median"))?,
                Self::display(field("p90"))?,
                Self::display(field("n").or(Some(&Value::from(0))))?
            ));
        }
        let mut lifecycle = String::new();
        Self::write_json(
            data.get("lifecycle_calls_by_subcommand_total")
                .unwrap_or(&Value::Null),
            0,
            false,
            true,
            &mut lifecycle,
        )?;
        lines.extend([
            String::new(),
            format!(
                "- lifecycle share of tool calls: {}%",
                Self::display(data.get("lifecycle_share_of_tool_calls_pct"))?
            ),
            format!(
                "- injected tokens vs new input: {}%",
                Self::display(data.get("injected_tokens_vs_new_input_pct"))?
            ),
            format!("- lifecycle subcommands: {lifecycle}"),
            String::new(),
        ]);
        Some(())
    }

    fn display(value: Option<&Value>) -> Option<String> {
        Some(match value.unwrap_or(&Value::Null) {
            Value::Null => "None".into(),
            Value::Bool(value) => if *value { "True" } else { "False" }.into(),
            Value::String(value) => value.clone(),
            Value::Number(value) => Self::number(value)?,
            _ => return None,
        })
    }

    fn number(value: &serde_json::Number) -> Option<String> {
        if value.is_f64() {
            Some(Number::float(
                value.as_f64().filter(|value| value.is_finite())?,
            ))
        } else {
            Some(value.to_string())
        }
    }

    fn quote(text: &str, ascii: bool) -> Option<String> {
        let escaped = serde_json::to_string(text).ok()?;
        if !ascii {
            return Some(escaped);
        }
        let mut result = String::new();
        for character in escaped.chars() {
            if character >= '\u{7f}' {
                for unit in character.encode_utf16(&mut [0; 2]) {
                    result.push_str(&format!("\\u{unit:04x}"));
                }
            } else {
                result.push(character);
            }
        }
        Some(result)
    }

    fn write_json(
        value: &Value,
        level: usize,
        pretty: bool,
        ascii: bool,
        out: &mut String,
    ) -> Option<()> {
        if level > 128 {
            return None;
        }
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(value) => out.push_str(if *value { "true" } else { "false" }),
            Value::Number(value) => out.push_str(&Self::number(value)?),
            Value::String(value) => out.push_str(&Self::quote(value, ascii)?),
            Value::Array(values) => {
                out.push('[');
                for (index, value) in values.iter().enumerate() {
                    Self::item_prefix(out, index, level, pretty);
                    Self::write_json(value, level + 1, pretty, ascii, out)?;
                }
                Self::closing(out, values.is_empty(), level, pretty, ']');
            }
            Value::Object(values) => {
                out.push('{');
                for (index, (key, value)) in values.iter().enumerate() {
                    Self::item_prefix(out, index, level, pretty);
                    out.push_str(&Self::quote(key, ascii)?);
                    out.push_str(": ");
                    Self::write_json(value, level + 1, pretty, ascii, out)?;
                }
                Self::closing(out, values.is_empty(), level, pretty, '}');
            }
        }
        Some(())
    }

    fn item_prefix(out: &mut String, index: usize, level: usize, pretty: bool) {
        if index != 0 {
            out.push(',');
            if !pretty {
                out.push(' ');
            }
        }
        if pretty {
            out.push('\n');
            out.push_str(&"  ".repeat(level + 1));
        }
    }

    fn closing(out: &mut String, empty: bool, level: usize, pretty: bool, character: char) {
        if pretty && !empty {
            out.push('\n');
            out.push_str(&"  ".repeat(level));
        }
        out.push(character);
    }
}

#[cfg(test)]
#[path = "overhead_report_text_tests.rs"]
mod tests;
