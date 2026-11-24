//! owner: ordered E2E hook smoke steps against the caller's scratch repository.
//! allowed imports: source and encoding guards, local file checks, fixed subprocesses.
//! forbidden imports: mutation of a real project, workflow authority, network clients.
//! callers/tests: run_smoke_checks and process parity fixtures.
//! verification: exact order, positive and negative assertions, and scratch admission.
#[cfg(unix)]
use crate::smoke_workspace::SmokeWorkspace;
use crate::{
    callback_state::LocalState, pretool_guard::CallbackGuard, python_encoding::PythonEncoding,
};
use serde_json::Value;
use std::{
    env,
    ffi::{OsStr, OsString},
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    process::Command,
};

const GATE_FIXTURE: &str = include_str!("../smoke-gate-records.json");

pub(crate) struct SmokeHookSuite {
    root: PathBuf,
    project: PathBuf,
    python: OsString,
}

impl SmokeHookSuite {
    pub(crate) fn run(launcher: &OsStr, args: &[OsString]) -> i32 {
        #[cfg(unix)]
        if let [python] = args {
            return Self::cli(launcher, python);
        }
        let Some((suite, records)) = Self::admit(launcher, args) else {
            return 125;
        };
        Self::status(suite.checks(&records))
    }

    fn status(result: Result<(), String>) -> i32 {
        match result {
            Ok(()) => 0,
            Err(error) => {
                println!("\n❌ Smoke check failed: {error}");
                1
            }
        }
    }

    #[cfg(unix)]
    fn cli(launcher: &OsStr, python: &OsStr) -> i32 {
        let temp = env::temp_dir();
        let Some(root) = Self::source(launcher, python) else {
            return 125;
        };
        if !temp.is_absolute()
            || temp.to_str().is_none()
            || env::vars_os().any(|(key, _)| {
                let key = key.to_string_lossy();
                key.starts_with("GIT_")
                    && !matches!(
                        key.as_ref(),
                        "GIT_CONFIG_GLOBAL"
                            | "GIT_CONFIG_NOSYSTEM"
                            | "GIT_OPTIONAL_LOCKS"
                            | "GIT_TERMINAL_PROMPT"
                    )
            })
        {
            return 125;
        }
        let Some(records) = Self::records() else {
            return 125;
        };
        println!("==================================================");
        println!("Starting E2E Hook Smoke Checks");
        println!("==================================================");
        let result = SmokeWorkspace::allocate(&temp).and_then(|workspace| {
            workspace.prepare(&root)?;
            let suite = Self {
                root,
                project: workspace.path().to_owned(),
                python: python.to_owned(),
            };
            suite.checks(&records).map_err(io::Error::other)
        });
        if result.is_ok() {
            println!("\n==================================================");
            println!("✅ All E2E smoke checks passed successfully!");
            println!("==================================================");
        }
        Self::status(result.map_err(|error| error.to_string()))
    }

    fn source(launcher: &OsStr, python: &OsStr) -> Option<PathBuf> {
        let root = CallbackGuard::root(launcher, "run_smoke_checks.py")?;
        root.to_str()?;
        python.to_str()?;
        let fixture = root.join("native/checkout-identity/smoke-gate-records.json");
        if LocalState::read(&fixture, GATE_FIXTURE.len() as u64)? != GATE_FIXTURE {
            return None;
        }
        (PythonEncoding::utf8() && Path::new(python).is_absolute() && Path::new(python).is_file())
            .then_some(root)
    }

    fn admit(launcher: &OsStr, args: &[OsString]) -> Option<(Self, Vec<String>)> {
        let [python, project] = args else { return None };
        let project = PathBuf::from(project);
        let physical = project.canonicalize().ok()?;
        let scratch = env::temp_dir().canonicalize().ok()?;
        let root = Self::source(launcher, python)?;
        project.to_str()?;
        if !project.is_absolute()
            || physical.parent()? != scratch
            || physical == root
            || !fs::symlink_metadata(project.join(".git")).ok()?.is_dir()
            || !LocalState::absent_dir(&project.join(".moru"))?
            || LocalState::read(&project.join("README.md"), 13)? != "Dummy project"
            || !fs::symlink_metadata(project.join(".vibeguard.json"))
                .ok()?
                .is_file()
        {
            return None;
        }
        let gates = Self::records()?;
        Some((
            Self {
                root,
                project,
                python: python.clone(),
            },
            gates,
        ))
    }

    fn records() -> Option<Vec<String>> {
        let records: Value = serde_json::from_str(GATE_FIXTURE).ok()?;
        let gates = records
            .as_array()?
            .iter()
            .map(|item| Some(item.get("gate")?.as_str()?.to_owned()))
            .collect::<Option<Vec<_>>>()?;
        (!gates.is_empty()).then_some(gates)
    }

    fn checks(&self, gates: &[String]) -> Result<(), String> {
        println!("\n--- Test 1: Start hook (triage command) ---");
        let (success, stdout, stderr) = self.hook(
            "start",
            &[
                "--command",
                "triage",
                "--request",
                "재검증해줘 이제 코덱스가 마무리했네",
            ],
        )?;
        if !success {
            return Err(format!(
                "Start hook failed:\nSTDOUT: {stdout}\nSTDERR: {stderr}"
            ));
        }
        println!("SUCCESS: Start hook completed successfully.");
        let state = self.project.join(".moru");
        let legacy = state.join("preflight.json");
        let evidence = if legacy.is_file() {
            legacy
        } else {
            fs::read_dir(state.join("runs"))
                .into_iter()
                .flatten()
                .flatten()
                .map(|entry| entry.path().join("preflight.json"))
                .filter(|path| path.is_file())
                .min()
                .ok_or("preflight.json was not created!")?
        };
        let evidence = evidence.to_str().ok_or("invalid preflight path")?;
        println!("SUCCESS: preflight.json exists.");

        println!("\n--- Test 2: Gate validation failures (checking constraints) ---");
        let (success, _, _) = self.hook(
            "gate",
            &[
                "--evidence",
                evidence,
                "--gate-name",
                "alignment brief",
                "--status",
                "SUCCESS",
                "--gate-evidence",
                "invalid brief without shared understanding phrase",
            ],
        )?;
        if success {
            return Err(
                "Gate should have failed validation due to missing required phrases!".into(),
            );
        }
        println!("SUCCESS: Gate validation correctly rejected weak alignment brief.");

        println!("\n--- Test 3: Gate validation success ---");
        if !fs::symlink_metadata(&state).is_ok_and(|metadata| metadata.is_dir()) {
            return Err("scratch project state directory is unavailable".into());
        }
        let batch = state.join("smoke-gates.json");
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&batch)
            .and_then(|mut file| file.write_all(GATE_FIXTURE.as_bytes()))
            .map_err(|error| error.to_string())?;
        let (success, stdout, stderr) = self.hook(
            "gate-batch",
            &[
                "--evidence",
                evidence,
                "--gate-json",
                &batch.to_string_lossy(),
            ],
        )?;
        if !success {
            return Err(format!(
                "Failed to record the gate batch:\nSTDOUT: {stdout}\nSTDERR: {stderr}"
            ));
        }
        for gate in gates {
            if !stdout.contains(gate) && !stdout.contains("truncated") {
                return Err(format!(
                    "Gate {gate} is missing from the batch result:\n{stdout}"
                ));
            }
        }
        println!("SUCCESS: All gates populated with valid evidence.");

        println!("\n--- Test 4: Finish hook check ---");
        let (success, stdout, stderr) = self.hook(
            "finish",
            &[
                "--evidence",
                evidence,
                "--allow-vibeguard-review",
                "E2E testing in temporary directory",
            ],
        )?;
        if !success {
            return Err(format!(
                "Finish hook failed:\nSTDOUT: {stdout}\nSTDERR: {stderr}"
            ));
        }
        println!("SUCCESS: Finish hook approved completed triage workflow.");

        println!("\n--- Test 5: Workflow search query check ---");
        let (success, stdout, stderr) = self.command("workflow.py", &["query", "triage"])?;
        if !success {
            return Err(format!("Workflow query failed: {stderr}"));
        }
        if !stdout.to_lowercase().contains("triage") {
            return Err("Expected search results not found!".into());
        }
        println!("SUCCESS: Search query returned results correctly.");
        Ok(())
    }

    fn hook(&self, action: &str, extra: &[&str]) -> Result<(bool, String, String), String> {
        let project = self.project.to_string_lossy();
        let root = self.root.to_string_lossy();
        let mut args = vec![action, "--project", &project, "--rules", &root];
        args.extend_from_slice(extra);
        self.command("agent-hook.py", &args)
    }

    fn command(&self, script: &str, args: &[&str]) -> Result<(bool, String, String), String> {
        let script = self.root.join("scripts").join(script);
        println!(
            "Running command: {} {} {}",
            self.python.to_string_lossy(),
            script.display(),
            args.join(" ")
        );
        let output = Command::new(&self.python)
            .arg(script)
            .args(args)
            .current_dir(&self.root)
            .output()
            .map_err(|error| error.to_string())?;
        let decode = |bytes| {
            String::from_utf8(bytes)
                .map(|text| text.replace("\r\n", "\n").replace('\r', "\n"))
                .map_err(|error| error.to_string())
        };
        Ok((
            output.status.success(),
            decode(output.stdout)?,
            decode(output.stderr)?,
        ))
    }
}
