//! Owner: ordinary HQ decision CLI argument selection, report delivery and diagnostics.
//! Allowed imports: HQ ID, assembly and atomic replacement owners, argv, selected environment and clock.
//! Forbidden imports: arbitrary write destinations, providers, Python and fallback after writes.
//! Callers/tests: completion probe and HQ decision CLI fixtures.
use super::{hq_report_assembly, hq_report_replace, hq_report_run_id::HqReportRunId};
use crate::{discovery_fs::DiscoveryFs, text::Text};
use serde_json::{json, Value};
use std::{
    env, io,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

const DENIED: &str = "not an HQ-dispatched run (MORU_HQ_RUN_ID unset or invalid) or empty question; record the blocker in the Moru checkpoint and ask the user instead\n";

#[derive(Default)]
struct Args<'a> {
    project: Option<&'a str>,
    question: Option<&'a str>,
    evidence: &'a str,
    result: &'a str,
    options: Vec<&'a str>,
}

impl<'a> Args<'a> {
    fn parse(request: &'a Value) -> Option<Self> {
        let fields = request.as_object()?;
        if fields.len() != 1 {
            return None;
        }
        let mut args = fields.get("argv")?.as_array()?.iter().map(Value::as_str);
        if args.next()?? != "decision" {
            return None;
        }
        let mut parsed = Self::default();
        while let Some(item) = args.next() {
            let item = item?;
            let (flag, value) = match item.split_once('=') {
                Some(pair) => pair,
                None => {
                    let value = args.next()??;
                    if value.starts_with('-') {
                        return None;
                    }
                    (item, value)
                }
            };
            match flag {
                "--project" => parsed.project = Some(value),
                "--question" => parsed.question = Some(value),
                "--evidence" => parsed.evidence = value,
                "--result" => parsed.result = value,
                "--option" => parsed.options.push(value),
                _ => return None,
            }
        }
        Some(parsed)
    }
}

fn reply(code: i32, stdout: &str, stderr: &str) -> Value {
    json!({"code":code,"stdout":stdout,"stderr":stderr})
}

fn variable(key: &str) -> Option<String> {
    match env::var_os(key) {
        Some(value) => value.into_string().ok(),
        None => Some(String::new()),
    }
}

pub(super) fn run(request: &Value) -> Option<io::Result<Value>> {
    let args = Args::parse(request)?;
    let raw_project = args.project?;
    let question = args.question?;
    if raw_project.contains('\0') {
        return None;
    }
    let project = DiscoveryFs::resolve_allow_missing(Path::new(if raw_project.is_empty() {
        "."
    } else {
        raw_project
    }))?;
    match std::fs::metadata(&project) {
        Ok(meta) if meta.is_dir() => {}
        Err(error) if !matches!(error.raw_os_error(), Some(libc::ENOENT | libc::ENOTDIR)) => {
            return None
        }
        _ => {
            return Some(Ok(reply(
                2,
                "",
                "decision report refused: --project is not a directory\n",
            )))
        }
    }
    let selected = HqReportRunId::resolve(
        &json!({"env_id":variable("MORU_HQ_RUN_ID")?, "preflight_id":null,"origin":null,"agent_id":null}),
    )?;
    let run = selected["run_id"].as_str()?;
    if run.is_empty() || Text::py_strip(question).is_empty() {
        return Some(Ok(reply(2, "", DENIED)));
    }
    let mut context = json!({});
    for key in [
        "MORU_HQ_TASK_ID",
        "MORU_HQ_PROJECT_ID",
        "MORU_HQ_OPERATOR_LABEL",
    ] {
        context[key] = json!(variable(key)?);
    }
    let project_name = project.file_name().unwrap_or_default().to_str()?;
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_millis();
    let assembly = hq_report_assembly::assemble(
        &json!({
            "run_id":run,"project_name":project_name,"env":context,"finished_at":i64::try_from(millis).ok()?,
            "question":question,"evidence":args.evidence,"result":args.result,"options":args.options
        }),
        true,
    )?;
    if assembly.get("skipped") == Some(&Value::Bool(true)) {
        return Some(Ok(reply(2, "", DENIED)));
    }
    let target = project.join(".moru/hq/reports").join(format!("{run}.json"));
    let success = format!("HQ decision report: {}\nNow checkpoint the Moru run with this blocker and end the turn; do not continue building.\n",target.to_str()?);
    let outcome = hq_report_replace::replace(
        &json!({"run_id":run,"project":project.to_str()?,"encoded":assembly.get("encoded")?.as_str()?}),
    )?;
    let response = match outcome {
        Ok(_) => reply(0, &success, ""),
        Err(_) => reply(
            1, "",
            "decision report failed: native HQ report replacement outcome could not be determined\n",
        ),
    };
    Some(Ok(response))
}
