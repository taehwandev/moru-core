//! owner: assembly and Markdown rendering of doctor reports from observed facts.
//! allowed imports: JSON and standard-library formatting.
//! forbidden imports: filesystem, process execution, providers and permission grants.
//! callers/tests: completion probe, Python doctor CLI and output parity fixtures.
//! verification: stable status, recommendations, UTF-8 and Markdown layout.
use serde_json::{json, Value};

pub(super) struct DoctorReport;

impl DoctorReport {
    pub(super) fn build(payload: &Value) -> Option<Value> {
        let facts = payload.get("facts")?;
        let template = payload.get("routing_template")?.as_str()?;
        let render_markdown = payload.get("markdown")?.as_bool()?;
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
        let markdown = if render_markdown {
            Some(Self::markdown(&report, &recommendations)?)
        } else {
            None
        };
        report["recommendations"] = json!(recommendations);
        Some(json!({"report": report, "markdown": markdown}))
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
