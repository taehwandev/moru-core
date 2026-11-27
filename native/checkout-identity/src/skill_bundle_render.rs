//! Owner: render skill bundle entrypoints and optional compatibility stubs.
//! Allowed imports: Python text semantics and JSON for ordinary relative paths.
//! Forbidden imports: filesystem access, link rewriting and migration effects.
//! Callers/tests: completion probe and skill bundle migration fixtures.
use crate::python_text::PythonText;
use serde_json::{json, Value};

fn path(raw: &str) -> Option<Vec<&str>> {
    if !raw.is_ascii() || raw.bytes().any(|b| b.is_ascii_control()) {
        return None;
    }
    let parts: Vec<_> = raw.split('/').collect();
    parts
        .iter()
        .all(|part| !matches!(*part, "" | "." | ".."))
        .then_some(parts)
}

fn relative(target: &[&str], base: &[&str]) -> String {
    let common = target.iter().zip(base).take_while(|(a, b)| a == b).count();
    let mut parts = vec![".."; base.len() - common];
    parts.extend_from_slice(&target[common..]);
    if parts.is_empty() {
        ".".into()
    } else {
        parts.join("/")
    }
}

fn key(raw: &str, suffix: &str) -> String {
    let parts: Vec<_> = raw
        .split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|part| !part.is_empty())
        .collect();
    format!("sys_{}_{suffix}", parts.join("_").to_ascii_lowercase())
}

fn title(text: &str, source: &str) -> Option<String> {
    for line in PythonText::splitlines(text) {
        if let Some(title) = line.strip_prefix("# ") {
            return Some(title.trim_matches(PythonText::whitespace).to_owned());
        }
    }
    let stem = source.strip_suffix(".md")?;
    if stem.chars().all(|ch| ch == '.') {
        return None;
    }
    let mut previous_cased = false;
    Some(
        stem.chars()
            .map(|ch| {
                let rendered = if ch == '-' {
                    ' '
                } else if previous_cased {
                    ch.to_ascii_lowercase()
                } else {
                    ch.to_ascii_uppercase()
                };
                previous_cased = ch.is_ascii_alphabetic();
                rendered
            })
            .collect(),
    )
}

pub(super) fn render(request: &Value) -> Option<Value> {
    let source = request.get("source")?.as_str()?;
    let skill = request.get("skill")?.as_str()?;
    let reference = request.get("reference")?.as_str()?;
    let source_parts = path(source)?;
    let skill_parts = path(skill)?;
    let ref_parts = path(reference)?;
    let title = title(request.get("text")?.as_str()?, source_parts.last()?)?;
    let skill_key = key(skill, "skill");
    let rendered = format!("---\nkeyflow_id: {skill_key}\nstatus: review\ntype: ai-generated\n---\n\n# {title}\n\nUse when the active route selects this skill or its topic applies.\n\nRead `references/current-guidance.md` for applicable decision rules, stop\nconditions and verification before acting. Open related cards only for\nin-scope work, starting with their `SKILL.md`. Use this canonical bundle,\nnot legacy flat paths.\n\nWhen changing routing, confirm it selects this entrypoint. When changing\nguidance, validate the reference's links and frontmatter.\n");
    let stub = if request.get("keep_stub")?.as_bool()? {
        let base = &source_parts[..source_parts.len() - 1];
        let skill_link = relative(&skill_parts, base);
        let ref_link = relative(&ref_parts, base);
        let stub_key = key(source, "compat");
        Some(format!("---\nkeyflow_id: {stub_key}\nstatus: review\ntype: compatibility-entrypoint\nmoru_skill_bundle_stub: true\n---\n\n# {title}\n\nThis compatibility path has moved to the Moru Core skill-bundle layout.\n\n## Read\n\n- `{skill_link}` for the canonical lightweight entrypoint.\n- `{ref_link}` for the full detailed guidance that previously lived here.\n\n## Verification\n\nRoutes should load `{skill}` instead of this compatibility stub.\n"))
    } else {
        None
    };
    Some(json!({"skill":rendered,"stub":stub}))
}
