//! Owner: work-cards list/closed-settlement ingress and JSON formatting.
//! Allowed: std, serde_json, card owners and existing source/FS/time readers.
//! Forbidden: SQL, schema creation/migrations, resume, lifecycle/liveness, caches.
//! Callers/tests: launcher_main; native card tests and transported smoke.
use crate::{
    cards_identity::CardRepository, cards_settlement::CardSettlement, cards_store::CardStore,
    discovery_fs::DiscoveryFs, pretool_guard::CallbackGuard, status_snapshot::StatusSnapshot,
    statusline::Renderer,
};
use serde_json::Value;
use std::{collections::BTreeMap, env, ffi::OsString, io::Write, path::PathBuf};

pub(crate) struct CardsProcess;

impl CardsProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        // Keep bundled dependency notices in distributed binaries as well as
        // in the source checkout required by the installation contract.
        std::hint::black_box(include_str!("../SQLITE-NOTICES.txt"));
        if let Some((code, output)) = close(launcher, &args[1..]) {
            let result = if code == 0 {
                std::io::stdout().write_all(output.as_bytes())
            } else {
                std::io::stderr().write_all(output.as_bytes())
            };
            return if result.is_ok() { code } else { 1 };
        }
        let Some(output) = snapshot(launcher, &args[1..]) else {
            crate::exec_python(launcher, args);
        };
        match std::io::stdout().write_all(output.as_bytes()) {
            Ok(()) => 0,
            Err(_) => 1,
        }
    }
}

fn snapshot(launcher: &OsString, args: &[OsString]) -> Option<String> {
    let words = args
        .iter()
        .map(|s| s.to_str())
        .collect::<Option<Vec<_>>>()?;
    let cwd = env::current_dir().ok()?;
    let (project, all) = match words.as_slice() {
        ["list"] => (cwd, false),
        ["list", "--all"] => (cwd, true),
        ["--project", path, "list"] => (PathBuf::from(path), false),
        ["--project", path, "list", "--all"] => (PathBuf::from(path), true),
        _ => return None,
    };
    let (project, state) = context(launcher, project)?;
    let Some(store) = CardStore::open(&state.join("work-cards/cards.sqlite3"))? else {
        return Some("[]\n".into());
    };
    let repo = CardRepository::key(&project)?;
    render(&store.list(&repo, all)?)
}

fn context(launcher: &OsString, project: PathBuf) -> Option<(PathBuf, PathBuf)> {
    let project = DiscoveryFs::resolve(&project)?;
    CallbackGuard::root(launcher, "git")?;
    let state = match env::var("MORU_STATE_HOME") {
        Ok(value) if !Renderer::strip(&value).is_empty() => PathBuf::from(Renderer::strip(&value)),
        Err(env::VarError::NotUnicode(_)) => return None,
        _ => PathBuf::from(env::var_os("HOME")?).join(".moru"),
    };
    Some((project, state))
}

fn close(launcher: &OsString, args: &[OsString]) -> Option<(i32, String)> {
    let words = args
        .iter()
        .map(|s| s.to_str())
        .collect::<Option<Vec<_>>>()?;
    let (project, words) = match words.as_slice() {
        ["--project", path, rest @ ..] => (PathBuf::from(path), rest),
        rest => (env::current_dir().ok()?, rest),
    };
    let (work, state) = match words {
        ["close", work] => (*work, "done"),
        ["close", work, "--state", state @ ("done" | "cancelled")] => (*work, *state),
        _ => return None,
    };
    if work.len() != 32
        || !work
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return None;
    }
    // Preserve Python's user-store protection for test process trees.
    if env::var("MORU_STATE_HOME")
        .ok()
        .is_none_or(|s| Renderer::strip(&s).is_empty())
        && env::var("MORU_UNDER_UNITTEST")
            .map(|s| !Renderer::strip(&s).is_empty())
            .unwrap_or_else(|error| matches!(error, env::VarError::NotUnicode(_)))
    {
        return None;
    }
    let (project, home) = context(launcher, project)?;
    let repo = CardRepository::key(&project)?;
    let stamp = StatusSnapshot::capture_time()?;
    let store = CardSettlement::open(&home.join("work-cards/cards.sqlite3"))?;
    Some(match store.settle(&repo, work, state, &stamp) {
        Ok(true) => (
            0,
            format!("{{\"state\": \"{state}\", \"work_id\": \"{work}\"}}\n"),
        ),
        Ok(false) => (
            2,
            "work cards: no active card with that work id in this repository\n".into(),
        ),
        Err(message) => (2, format!("work cards: {message}\n")),
    })
}

fn render(cards: &[BTreeMap<String, Value>]) -> Option<String> {
    let mut rows = Vec::new();
    for card in cards {
        let mut fields = Vec::new();
        for (name, value) in card {
            fields.push(format!(
                "{}: {}",
                serde_json::to_string(name).ok()?,
                serde_json::to_string(value).ok()?
            ));
        }
        rows.push(format!("{{{}}}", fields.join(", ")));
    }
    Some(format!("[{}]\n", rows.join(", ")))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn output_keeps_python_spacing_unicode_and_nulls() {
        let mut row = BTreeMap::new();
        row.insert("summary".into(), serde_json::json!("한글😀\n"));
        row.insert("command".into(), Value::Null);
        assert_eq!(
            render(&[row]).unwrap(),
            "[{\"command\": null, \"summary\": \"한글😀\\n\"}]\n"
        );
    }
}
