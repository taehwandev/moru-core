//! owner: OverheadReportText; allowed imports: serde_json, shared Python text and JSON, std;
//! forbidden imports: I/O, runtime Python, providers; callers/tests: overhead report CLI;
//! verification: JSON/Markdown formatting parity with synthetic reports.
use crate::python_json::{PythonJson, Value};

pub(crate) struct OverheadReportText;

impl OverheadReportText {
    pub(crate) fn json(report: &serde_json::Value) -> Option<String> {
        Self::json_value(&PythonJson::parse(&report.to_string())?)
    }

    pub(crate) fn json_value(report: &Value) -> Option<String> {
        PythonJson::render(report, true, false)
    }

    #[cfg(test)]
    pub(crate) fn markdown(report: &serde_json::Value) -> Option<String> {
        Self::markdown_value(&PythonJson::parse(&report.to_string())?)
    }

    pub(crate) fn markdown_value(report: &Value) -> Option<String> {
        let window = report.get("window")?.as_object()?;
        let mut lines = vec![
            "# Moru workflow overhead".into(),
            String::new(),
            format!(
                "Generated: {}  ",
                PythonJson::string(report.get("generated_at")?)
            ),
            format!(
                "Window: {} .. {}",
                PythonJson::string(window.get("since")?),
                PythonJson::string(window.get("until")?)
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
            .iter()
        {
            let stats = value.as_object()?;
            lines.push(format!(
                "| {key} | {} | {} | {} |",
                Self::display(stats.get("n")),
                Self::display(stats.get("median")),
                Self::display(stats.get("p90"))
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
                    PythonJson::string(item.get("count")?),
                    PythonJson::string(item.get("message")?)
                ));
            }
        }
        Some(lines.join("\n") + "\n")
    }

    fn sessions(report: &Value, name: &str) -> Option<String> {
        Some(PythonJson::string(report.get(name)?.get("sessions")?))
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
                None => None,
                Some(value) if !PythonJson::truthy(value) => None,
                Some(value) => Some(value.as_object()?),
            };
            let field = |key| stats.and_then(|stats| stats.get(key));
            lines.push(format!(
                "| {label} | {} | {} | {} |",
                Self::display(field("median")),
                Self::display(field("p90")),
                field("n")
                    .map(PythonJson::string)
                    .unwrap_or_else(|| "0".into())
            ));
        }
        let lifecycle = PythonJson::render(
            data.get("lifecycle_calls_by_subcommand_total")
                .unwrap_or(&Value::Null),
            false,
            true,
        )?;
        lines.extend([
            String::new(),
            format!(
                "- lifecycle share of tool calls: {}%",
                Self::display(data.get("lifecycle_share_of_tool_calls_pct"))
            ),
            format!(
                "- injected tokens vs new input: {}%",
                Self::display(data.get("injected_tokens_vs_new_input_pct"))
            ),
            format!("- lifecycle subcommands: {lifecycle}"),
            String::new(),
        ]);
        Some(())
    }

    fn display(value: Option<&Value>) -> String {
        PythonJson::string(value.unwrap_or(&Value::Null))
    }
}

#[cfg(test)]
#[path = "overhead_report_text_tests.rs"]
mod tests;
