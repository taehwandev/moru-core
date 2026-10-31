//! Read-only quiet-state proof under existing Python-compatible locks.
use crate::callback_state::LocalState as State;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    env,
    fs::{self, File},
    path::{Path, PathBuf},
};

pub(crate) struct Mailboxes {
    project: PathBuf,
    reference: PathBuf,
    locks: Vec<File>,
}

impl Mailboxes {
    pub(crate) fn quiet(project: &Path, runtime: &str) -> Option<Self> {
        let state = env::var("MORU_STATE_HOME")
            .ok()
            .filter(|v| !v.trim().is_empty())
            .map(|v| PathBuf::from(crate::statusline::Renderer::strip(&v)))
            .unwrap_or(PathBuf::from(env::var_os("HOME")?).join(".moru"));
        if !state.is_absolute() {
            return None;
        }
        let state = state
            .parent()?
            .canonicalize()
            .ok()?
            .join(state.file_name()?);
        let id = moru_checkout_identity::CheckoutIdentity::repository_key(project.to_str()?)?;
        let mut proof = Self {
            project: project.to_owned(),
            reference: state.join("agent-mailbox").join(id),
            locks: Vec::new(),
        };
        State::safe_path(&state, &proof.reference)?;
        let local = project.join(".moru/agent-mailbox");
        State::safe_path(project, &local)?;
        for root in [&local, &proof.reference] {
            if State::absent_dir(root)? {
                continue;
            }
            proof.locks.push(State::lock(&root.join(".mailbox.lock"))?);
            for category in ["inbox", "leases"] {
                let path = root.join(category).join(runtime);
                State::safe_path(root, &path)?;
                State::empty(&path)?;
            }
        }
        Some(proof)
    }

    pub(crate) fn prompt_ready(mut self, core: &Path, runtime: &str, session: &str) -> Option<()> {
        self.tasks_empty()?;
        self.guidance_ready(core, runtime, session)
    }

    pub(crate) fn tasks_empty(&mut self) -> Option<()> {
        let tasks = self.project.join(".moru/agent-mailbox/task-continuation");
        State::safe_path(&self.project, &tasks)?;
        if !State::absent_dir(&tasks)? {
            self.locks.push(State::lock(&tasks.join(".tasks.lock"))?);
            // Any record or budget can have prompt-boundary effects: replay it.
            for entry in fs::read_dir(&tasks).ok()? {
                let entry = entry.ok()?;
                if entry.file_name() != ".tasks.lock" {
                    return None;
                }
            }
        }
        Some(())
    }

    fn guidance_ready(&self, core: &Path, runtime: &str, session: &str) -> Option<()> {
        let source = State::read(
            &core.join("common/skills/agent-operating-skill/SKILL.md"),
            32768,
        )?;
        let text = source
            .split_once("## Live Session Continuity\n")?
            .1
            .split("\n## ")
            .next()?;
        let text = crate::statusline::Renderer::strip(text);
        if text.is_empty() || text.chars().count() > 4000 {
            return None;
        }
        let identity = format!(
            "{:x}",
            Sha256::digest(format!("{runtime}:{session}").as_bytes())
        );
        let path = self
            .reference
            .join("guidance")
            .join(format!("{identity}.json"));
        State::safe_path(&self.reference, &path)?;
        let seen: Value = serde_json::from_str(&State::read(&path, 4096)?).ok()?;
        let digest = format!("{:x}", Sha256::digest(text.as_bytes()));
        (seen.is_object() && seen.get("sha256")?.as_str()? == digest).then_some(())
    }
}
