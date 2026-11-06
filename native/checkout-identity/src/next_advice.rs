//! owner: NextAdvice; allowed imports: PythonJson, PythonText, Verification, serde_json, std;
//! forbidden imports: state writes, subprocess, gate validation; callers/tests: NextProcess;
//! verification: explicit-evidence remaining-gate parity, generated canonical templates.
use crate::{
    next_verification::Verification,
    python_json::{PythonJson as Py, Value as PyValue},
    python_text::PythonText,
};
use serde_json::{json, Value};
use std::{collections::BTreeSet, path::Path};
include!(concat!(env!("OUT_DIR"), "/next_contract.rs"));
pub(super) struct NextAdvice;
impl NextAdvice {
    pub fn render(
        project: &Path,
        evidence: &Path,
        preflight: &PyValue,
        verification: &Verification,
        format: &str,
        launcher: &Path,
        recorded: &BTreeSet<String>,
    ) -> Option<String> {
        let contract: Value = serde_json::from_str(CONTRACT).ok()?;
        let p = preflight.as_object()?;
        let empty = crate::python_json::Object::new();
        if p.get("route")
            .is_some_and(|v| !matches!(v, PyValue::Null | PyValue::Object(_)))
        {
            return None;
        }
        let route = match p.get("route").filter(|v| Py::truthy(v)) {
            Some(v) => v.as_object()?,
            None => &empty,
        };
        if ["gates", "required_docs"].iter().any(|key| {
            route
                .get(key)
                .is_some_and(|v| !matches!(v, PyValue::Null | PyValue::Array(_)))
        }) {
            return None;
        }
        let full_gates = match route.get("gates").filter(|v| Py::truthy(v)) {
            Some(v) => v
                .as_array()?
                .iter()
                .filter_map(PyValue::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>(),
            None => Vec::new(),
        };
        let gates = full_gates
            .iter()
            .filter(|gate| !recorded.contains(*gate))
            .cloned()
            .collect::<Vec<_>>();
        let skills = Self::skills(&contract, route)?;
        let prefix = format!("{}", launcher.to_str()?);
        let project = project.to_str()?;
        let evidence_text = evidence.to_str()?;
        let (step, command, shape) = Self::decision(
            &contract,
            &prefix,
            project,
            evidence_text,
            &gates,
            &skills,
            &full_gates,
        )?;
        let field = |key: &str| p.get(key).filter(|v| Py::truthy(v)).map(Py::string);
        let run =
            field("agent_run_id").unwrap_or(evidence.parent()?.file_name()?.to_str()?.to_owned());
        let work = match p.get("work").filter(|v| Py::truthy(v)) {
            Some(v) => v
                .as_object()?
                .get("id")
                .filter(|v| Py::truthy(v))
                .map(Py::string)
                .unwrap_or_default(),
            None => String::new(),
        };
        let route_name = route
            .get("command")
            .filter(|v| Py::truthy(v))
            .map(Py::string)
            .unwrap_or_default();
        let (gate_repr, templates) = Self::templates(&contract, &gates, &skills)?;
        if format == "json" {
            let info = json!({"status":"active_run","project":project,"run_id":run,"work_id":work,"command":route_name,"evidence":evidence_text,"remaining_gates":gates,"loaded_skills":skills,"next_step":step,"copyable_command":command,"template_lines":templates,"review_shape":shape,"verification":serde_json::from_str::<Value>(&verification.json()).ok()?});
            return Some(Self::json(&info) + "\n");
        }
        let mut lines = vec![
            "SUCCESS next".to_string(),
            format!("- run id: {run} (route: {route_name})"),
            format!("- evidence: {evidence_text}"),
            format!("- remaining gates: {gate_repr}"),
            format!("- next step: {step}"),
            format!("- copyable command: {command}"),
        ];
        lines.extend(templates.iter().skip(1).map(|t| format!("- {t}")));
        if !verification.commands.is_empty() {
            lines.push("- suggested fast verification for changed files:".into());
            lines.extend(verification.commands.iter().map(|c| format!("  * {c}")));
        }
        Some(lines.join("\n") + "\n")
    }
    fn skills(contract: &Value, route: &crate::python_json::Object) -> Option<Vec<String>> {
        let mut skills = BTreeSet::new();
        if let Some(docs) = route.get("required_docs").filter(|v| Py::truthy(v)) {
            for doc in docs.as_array()? {
                let text = Py::string(doc).replace('\\', "/");
                let parts = text
                    .split('/')
                    .filter(|p| !p.is_empty())
                    .collect::<Vec<_>>();
                for pair in parts.windows(2) {
                    if contract["containers"]
                        .as_array()?
                        .iter()
                        .any(|v| v.as_str() == Some(pair[0]))
                    {
                        let skill = pair[1]
                            .trim_matches(PythonText::whitespace)
                            .to_lowercase()
                            .replace('-', "_");
                        let skill = contract["aliases"]
                            .get(&skill)
                            .and_then(Value::as_str)
                            .unwrap_or(&skill);
                        if (2..=81).contains(&skill.len())
                            && skill.as_bytes()[0].is_ascii_lowercase()
                            && skill
                                .bytes()
                                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
                        {
                            skills.insert(skill.to_string());
                        }
                        break;
                    }
                }
            }
        }
        Some(skills.into_iter().collect())
    }
    fn decision(
        contract: &Value,
        prefix: &str,
        project: &str,
        evidence_text: &str,
        gates: &[String],
        skills: &[String],
        full_gates: &[String],
    ) -> Option<(&'static str, String, String)> {
        let active_review = contract["review_gates"]
            .as_array()?
            .iter()
            .filter(|v| full_gates.iter().any(|g| Some(g.as_str()) == v.as_str()))
            .cloned()
            .collect::<Vec<_>>();
        let review = contract["reviews"]
            .as_array()?
            .iter()
            .find(|v| v["gates"].as_array() == Some(&active_review))?;
        let (step, command) = if let Some(index) = gates.iter().position(|g| g == "review hook") {
            let before = gates[..index]
                .iter()
                .filter(|g| g.as_str() != "commit readiness")
                .cloned()
                .collect::<Vec<_>>();
            if before.is_empty() {
                let flags = review["flags"]
                    .as_array()?
                    .iter()
                    .map(|v| Some(format!("{} \"<observed evidence>\"", v.as_str()?)))
                    .collect::<Option<Vec<_>>>()?
                    .join(" ");
                ("review",format!("{prefix} review --project {project} --evidence {evidence_text} --review-outcome <pass|findings> {flags}"))
            } else {
                (
                    "record_pre_review_gates",
                    Self::batch(&contract, &prefix, project, evidence_text, &before, &skills)?,
                )
            }
        } else {
            let manual = gates
                .iter()
                .filter(|g| g.as_str() != "commit readiness")
                .cloned()
                .collect::<Vec<_>>();
            if manual.is_empty() {
                (
                    "finish",
                    format!("{prefix} finish --project {project} --evidence {evidence_text}"),
                )
            } else {
                (
                    "record_closeout_gates",
                    Self::batch(&contract, &prefix, project, evidence_text, &manual, &skills)?,
                )
            }
        };
        let shape = if full_gates.iter().any(|g| g == "review hook") {
            review["shape"].as_str()?
        } else {
            ""
        };
        Some((step, command, shape.to_owned()))
    }
    fn templates(
        contract: &Value,
        gates: &[String],
        skills: &[String],
    ) -> Option<(String, Vec<String>)> {
        let gate_repr = format!(
            "[{}]",
            gates
                .iter()
                .map(|g| PythonText::repr(g))
                .collect::<Vec<_>>()
                .join(", ")
        );
        let mut templates = vec![format!("Remaining route gates: {gate_repr}")];
        for gate in gates {
            templates.push(
                if let Some(t) = contract["gates"]
                    .get(gate)
                    .and_then(|v| v["template"].as_str())
                {
                    t.to_owned()
                } else {
                    format!(
                        "fill-in template for {gate}: {}",
                        serde_json::to_string(&json!({"gate":gate,"status":"SUCCESS","fields":{}}))
                            .ok()?
                    )
                },
            );
            if gate == "retrospective check" && !skills.is_empty() {
                templates.push(format!(
                    "{}{}",
                    contract["skills_note"].as_str()?,
                    skills.join(", ")
                ));
            }
        }
        Some((gate_repr, templates))
    }
    fn batch(
        contract: &Value,
        launcher: &str,
        project: &str,
        evidence: &str,
        gates: &[String],
        skills: &[String],
    ) -> Option<String> {
        let mut records = Vec::new();
        for gate in gates {
            let mut fields = contract["gates"]
                .get(gate)
                .map(|v| v["fields"].clone())
                .unwrap_or_else(|| json!({}));
            if gate == "retrospective check" && !skills.is_empty() {
                fields["skills_checked"] = json!(skills.join(", "));
            }
            records.push(json!({"gate":gate,"status":"<SUCCESS or FAIL>","fields":fields}));
        }
        Some(format!(
            "{launcher} gate-batch --project {project} --evidence {evidence} --gate-record '{}'",
            serde_json::to_string(&records).ok()?
        ))
    }
    fn json(value: &Value) -> String {
        match value {
            Value::Object(map) => {
                let mut keys = map.keys().collect::<Vec<_>>();
                keys.sort();
                format!(
                    "{{{}}}",
                    keys.iter()
                        .map(|k| format!(
                            "{}: {}",
                            serde_json::to_string(k).unwrap(),
                            Self::json(&map[*k])
                        ))
                        .collect::<Vec<_>>()
                        .join(", ")
                )
            }
            Value::Array(values) => format!(
                "[{}]",
                values.iter().map(Self::json).collect::<Vec<_>>().join(", ")
            ),
            _ => serde_json::to_string(value).unwrap(),
        }
    }
}
#[cfg(test)]
#[path = "next_advice_tests.rs"]
mod tests;
