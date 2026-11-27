//! Owner: assemble finished and decision-needed HQ reports from selected values.
//! Allowed imports: bounded HQ encoding, Python text and JSON.
//! Forbidden imports: filesystem, environment, clocks and providers.
//! Callers/tests: completion probe and HQ report finish and decision tests.
use super::hq_report_encoding;
use crate::python_text::PythonText;
use serde_json::{json, Value};
use std::collections::HashSet;

fn line(value: &Value) -> Option<String> {
    if value.is_null() {
        return Some(String::new());
    }
    Some(
        value
            .as_str()?
            .split(PythonText::whitespace)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" "),
    )
}

fn first(values: &[&Value], default: &str) -> Option<String> {
    for value in values {
        let text = line(value)?;
        if !text.is_empty() {
            return Some(text);
        }
    }
    Some(default.to_owned())
}

fn safe_id(id: &str) -> bool {
    (1..=128).contains(&id.len())
        && !id.contains("..")
        && id.bytes().enumerate().all(|(i, b)| {
            b.is_ascii_alphanumeric() || b == b'_' || (i > 0 && matches!(b, b'.' | b'-'))
        })
}

fn finish(request: &Value, pre: &Value, env: &Value, payload: &mut Value) -> Option<()> {
    let mut result = first(
        &[
            &env["MORU_HQ_RESULT"],
            &pre["hq_result"],
            &pre["request_intake"]["target_summary"],
        ],
        "",
    )?;
    if result.is_empty() {
        let command = line(&pre["route"]["command"])?;
        result = if command.is_empty() {
            "finish passed".into()
        } else {
            format!("finish passed ({command})")
        };
    }
    let mut evidence = line(&env["MORU_HQ_EVIDENCE"])?;
    if evidence.is_empty() {
        let mut seen = HashSet::new();
        let mut gates = Vec::new();
        for gate in request.get("gates")?.as_array()? {
            let gate = line(gate)?;
            if !gate.is_empty() && seen.insert(gate.clone()) {
                gates.push(gate);
            }
        }
        evidence = if gates.is_empty() {
            "all required gates passed".into()
        } else {
            gates.join(", ")
        };
    }
    payload["status"] = json!("finished");
    payload["result"] = json!(result);
    payload["evidence"] = json!(evidence);
    payload["decisionNeeded"] = json!(first(
        &[&env["MORU_HQ_DECISION_NEEDED"], &pre["hq_decision_needed"]],
        ""
    )?);
    Some(())
}

fn decision_body(request: &Value, payload: &mut Value) -> Option<()> {
    let question = line(request.get("question")?)?;
    if question.is_empty() {
        return None;
    }
    let mut choices = Vec::new();
    for option in request.get("options")?.as_array()? {
        let option = line(option)?;
        if !option.is_empty() && choices.len() < 3 {
            choices.push(option.chars().take(60).collect::<String>());
        }
    }
    payload["status"] = json!("decision_needed");
    payload["result"] = json!(first(
        &[request.get("result")?],
        "stopped before building on a contradiction"
    )?);
    payload["evidence"] = json!(first(&[request.get("evidence")?], "contradiction found")?);
    payload["decisionNeeded"] = json!(question);
    payload["decisionOptions"] = json!(choices);
    Some(())
}

pub(super) fn assemble(request: &Value, decision: bool) -> Option<Value> {
    let run = request.get("run_id")?.as_str()?;
    if !safe_id(run) {
        return None;
    }
    let project = request.get("project_name")?.as_str()?;
    let env = request.get("env")?;
    env.as_object()?;
    let pre = if decision {
        &Value::Null
    } else {
        request.get("preflight")?
    };
    let mut payload = json!({
        "schema":1,"runId":run,
        "projectId":first(&[&env["MORU_HQ_PROJECT_ID"],&pre["hq_project_id"],&pre["project_id"]],project)?,
        "taskId":first(&[&env["MORU_HQ_TASK_ID"],&pre["hq_task_id"],&pre["task_id"],&pre["agent_run_id"]],run)?,
        "operatorLabel":first(&[&env["MORU_HQ_OPERATOR_LABEL"],&pre["hq_operator_label"],&pre["operator_label"]],"moru-core")?
    });
    if decision {
        decision_body(request, &mut payload)?;
    } else {
        pre.as_object()?;
        finish(request, pre, env, &mut payload)?;
    }
    payload["finishedAt"] = json!(request.get("finished_at")?.as_i64()?);
    loop {
        let result = hq_report_encoding::encode(&json!({"payload":payload,"max_bytes":500}))?;
        let encoded = result.get("encoded")?.as_str()?;
        if !decision || encoded.len() <= 500 {
            return Some(result);
        }
        // Remove the next option from the already-truncated report.
        payload = serde_json::from_str(encoded).ok()?;
        if payload["decisionOptions"].as_array_mut()?.pop().is_none() {
            return Some(json!({"skipped":true}));
        }
    }
}
