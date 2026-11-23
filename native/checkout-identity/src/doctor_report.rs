//! owner: assembly and rendering of doctor reports from observed facts.
//! allowed imports: JSON and standard-library formatting.
//! forbidden imports: filesystem, process execution, providers and permission grants.
//! callers/tests: completion probe, Python doctor CLI and output parity fixtures.
//! verification: stable status, recommendations and exact JSON and Markdown.
use serde_json::{json, Value};

pub(super) struct DoctorReport;

impl DoctorReport {
    pub(super) fn build(payload: &Value) -> Option<Value> {
        let facts = payload.get("facts")?;
        let template = payload.get("routing_template")?.as_str()?;
        let output_format = payload.get("format")?;
        let project = facts["project"].as_str()?;
        let launcher = facts["launchers"]["moru_launcher"].as_str()?;
        let warning = facts["launchers"]["launcher_issue"].as_str()?;
        let has_agents = facts["instructions"]["agents_md_present"].as_bool()?;
        let due = facts["state"]["project_memory"]["expired_or_due"].as_u64()?;
        let mut recommendations = Vec::new();
        if !warning.is_empty() {
            recommendations.push(warning.to_owned());
        }
        if !has_agents {
            recommendations.push(format!(
                "No AGENTS.md; add the managed routing block from `{template}`."
            ));
        }
        if due > 0 {
            recommendations.push(format!(
                "Project memory has {due} record(s) due for review; run `{launcher} project-memory consolidate --project {project}`."
            ));
        }
        let status = if warning.is_empty() {
            "ok"
        } else {
            "attention"
        };
        let mut report = json!({"status": status});
        report.as_object_mut()?.extend(facts.as_object()?.clone());
        report["recommendations"] = json!(&recommendations);
        let rendered = match output_format.as_str() {
            Some("markdown") => Some(Self::markdown(&report, &recommendations)?),
            Some("json") => {
                let mut output = String::new();
                Self::append_json(&report, &mut output)?;
                Some(output)
            }
            None if output_format.is_null() => None,
            _ => return None,
        };
        Some(json!({"report": report, "rendered": rendered}))
    }

    fn append_json(value: &Value, output: &mut String) -> Option<()> {
        match value {
            Value::Object(fields) => {
                let mut fields: Vec<_> = fields.iter().collect();
                fields.sort_unstable_by(|(left, _), (right, _)| left.cmp(right));
                output.push('{');
                for (index, (key, value)) in fields.into_iter().enumerate() {
                    if index != 0 {
                        output.push_str(", ");
                    }
                    output.push_str(&serde_json::to_string(key).ok()?);
                    output.push_str(": ");
                    Self::append_json(value, output)?;
                }
                output.push('}');
            }
            Value::Array(items) => {
                output.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index != 0 {
                        output.push_str(", ");
                    }
                    Self::append_json(item, output)?;
                }
                output.push(']');
            }
            // Doctor counts are integers. Preserve the reference formatting for
            // other numeric values without coercing them to integers.
            Value::Number(number) if !number.is_i64() && !number.is_u64() => return None,
            scalar => output.push_str(&serde_json::to_string(scalar).ok()?),
        }
        Some(())
    }

    fn markdown(report: &Value, recommendations: &[String]) -> Option<String> {
        let project = report["project"].as_str()?;
        let status = report["status"].as_str()?.to_ascii_uppercase();
        let stacks = report["stacks"]
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        let stacks = if stacks.is_empty() {
            "none".into()
        } else {
            stacks.join(", ")
        };
        let permission_count = report["detected_permission_count"].as_u64()?;
        let present = if report["instructions"]["agents_md_present"].as_bool()? {
            "present"
        } else {
            "missing"
        };
        let managed = if report["instructions"]["managed_routing_block"].as_bool()? {
            "yes"
        } else {
            "no"
        };
        let state = &report["state"];
        let root = state["active_state_dir"].as_str()?;
        let active = state["active_runs"].as_u64()?;
        let cards = state["open_work_cards"].as_u64()?;
        let memory = state["project_memory"]["active_records"].as_u64()?;
        let due = state["project_memory"]["expired_or_due"].as_u64()?;
        let mut text = format!(
            "Moru Doctor ({status}): {project}\n\
             - detected stacks: {stacks} (permissions: {permission_count})\n\
             - AGENTS.md: {present} (managed block: {managed})\n\
             - state root: {root}\n\
             - active runs: {active}, open work cards: {cards}, project memory: {memory} active ({due} due)"
        );
        if recommendations.is_empty() {
            text.push_str("\n- recommendations: none (healthy)");
        } else {
            text.push_str("\n- recommendations:");
            for item in recommendations {
                text.push_str("\n  * ");
                text.push_str(item);
            }
        }
        Some(text)
    }
}
