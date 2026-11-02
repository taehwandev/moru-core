//! Owner: read-only work-cards list ingress and JSON formatting.
//! Allowed: std, serde_json, cards_store/identity and existing source/FS readers.
//! Forbidden: close/resume, schema/data writes, lifecycle/liveness and caches.
//! Callers/tests: launcher_main; test_native_work_cards, transported smoke.
use crate::{
    cards_identity::CardRepository, cards_store::CardStore, discovery_fs::DiscoveryFs,
    pretool_guard::CallbackGuard, statusline::Renderer,
};
use serde_json::Value;
use std::{collections::BTreeMap, env, ffi::OsString, io::Write, path::PathBuf};

pub(crate) struct CardsProcess;

impl CardsProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        // Keep bundled dependency notices in distributed binaries as well as
        // in the source checkout required by the installation contract.
        std::hint::black_box(include_str!("../SQLITE-NOTICES.txt"));
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
    let project = DiscoveryFs::resolve(&project)?;
    CallbackGuard::root(launcher, "git")?;
    let state = match env::var("MORU_STATE_HOME") {
        Ok(value) if !Renderer::strip(&value).is_empty() => PathBuf::from(Renderer::strip(&value)),
        Err(env::VarError::NotUnicode(_)) => return None,
        _ => PathBuf::from(env::var_os("HOME")?).join(".moru"),
    };
    let Some(store) = CardStore::open(&state.join("work-cards/cards.sqlite3"))? else {
        return Some("[]\n".into());
    };
    let repo = CardRepository::key(&project)?;
    render(&store.list(&repo, all)?)
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
